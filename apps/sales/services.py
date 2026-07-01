from decimal import Decimal

from django.db import transaction
from django.db.models import F, Max, Sum
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Inventory, StockMovement
from apps.customers.models import Customer

from .models import CustomerBalanceEntry, Sale, SaleItem


def resolve_customer(tenant, customer_data):
    if not customer_data:
        return None

    customer_id = customer_data.get("id")
    if customer_id:
        try:
            return Customer.objects.get(pk=customer_id, tenant=tenant)
        except Customer.DoesNotExist as exc:
            raise ValidationError(
                {"customer": "Selected customer does not belong to the active tenant."}
            ) from exc

    return Customer.objects.create(
        tenant=tenant,
        name=customer_data["name"],
        reference=customer_data["reference"],
        phone=customer_data.get("phone", ""),
        notes=customer_data.get("notes", ""),
    )


def rebuild_customer_balances(customer):
    open_entries = customer.balance_entries.filter(status=CustomerBalanceEntry.Status.OPEN)
    customer.credit_balance = open_entries.filter(entry_type=CustomerBalanceEntry.EntryType.CREDIT).aggregate(
        total=Sum("amount")
    ).get("total") or Decimal("0.00")
    customer.debt_balance = open_entries.filter(entry_type=CustomerBalanceEntry.EntryType.DEBT).aggregate(
        total=Sum("amount")
    ).get("total") or Decimal("0.00")
    customer.save(update_fields=["credit_balance", "debt_balance", "updated_at"])


def allocate_stock_batches(inventory, quantity_units):
    remaining_units = quantity_units
    batches = inventory.batches.filter(units_remaining__gt=0).order_by(F("expiry_date").asc(nulls_last=True), "created_at")

    for batch in batches:
        if remaining_units <= 0:
            break
        deducted = min(batch.units_remaining, remaining_units)
        batch.units_remaining -= deducted
        batch.save(update_fields=["units_remaining", "updated_at"])
        remaining_units -= deducted

    if remaining_units > 0:
        raise ValidationError({"items": f"Batch allocation failed for {inventory.product.name}."})


def rebuild_sale_totals(sale):
    sale_items = list(sale.items.all())
    gross_total = sum((item.line_total for item in sale_items), Decimal("0.00"))
    paid_total = sum((item.amount_paid for item in sale_items), Decimal("0.00"))
    debt_total = sum((item.debt_amount for item in sale_items), Decimal("0.00"))
    credit_total = sum((item.credit_amount for item in sale_items), Decimal("0.00"))
    has_pending_items = any(item.is_pending for item in sale_items)

    sale.gross_total = gross_total
    sale.paid_total = paid_total
    sale.debt_total = debt_total
    sale.credit_total = credit_total
    sale.status = Sale.Status.OPEN if has_pending_items else Sale.Status.COMPLETED
    sale.save(update_fields=["gross_total", "paid_total", "debt_total", "credit_total", "status", "updated_at"])


@transaction.atomic
def regularize_pending_item(*, tenant, sale_item, mark_collected=False, regularize_amount=None):
    if sale_item.tenant_id != tenant.id:
        raise ValidationError({"detail": "Selected pending item does not belong to the active tenant."})

    item_fields_to_update = []

    if mark_collected and not sale_item.is_collected:
        sale_item.is_collected = True
        sale_item.pickup_status = SaleItem.PickupStatus.NOW
        item_fields_to_update.extend(["is_collected", "pickup_status"])

    if regularize_amount is not None:
        outstanding_debt = sale_item.debt_amount
        outstanding_credit = sale_item.credit_amount
        regularize_amount = Decimal(regularize_amount)

        if outstanding_debt > 0:
            if regularize_amount > outstanding_debt:
                raise ValidationError({"regularize_amount": "Amount exceeds the outstanding debt."})

            sale_item.amount_paid += regularize_amount
            remaining_debt = outstanding_debt - regularize_amount
            sale_item.payment_status = (
                SaleItem.PaymentStatus.NOW
                if remaining_debt == Decimal("0.00")
                else SaleItem.PaymentStatus.PARTIAL
            )
            sale_item.is_settled = remaining_debt == Decimal("0.00")
            item_fields_to_update.extend(["amount_paid", "payment_status", "is_settled"])

            debt_entry = sale_item.balance_entries.filter(
                status=CustomerBalanceEntry.Status.OPEN,
                entry_type=CustomerBalanceEntry.EntryType.DEBT,
            ).order_by("created_at").first()
            if debt_entry is not None:
                if remaining_debt == Decimal("0.00"):
                    debt_entry.status = CustomerBalanceEntry.Status.RESOLVED
                    debt_entry.save(update_fields=["status", "updated_at"])
                else:
                    debt_entry.amount = remaining_debt
                    debt_entry.save(update_fields=["amount", "updated_at"])
        elif outstanding_credit > 0:
            if regularize_amount > outstanding_credit:
                raise ValidationError({"regularize_amount": "Amount exceeds the outstanding credit."})

            sale_item.amount_paid -= regularize_amount
            remaining_credit = outstanding_credit - regularize_amount
            sale_item.payment_status = SaleItem.PaymentStatus.NOW
            sale_item.is_settled = remaining_credit == Decimal("0.00")
            item_fields_to_update.extend(["amount_paid", "payment_status", "is_settled"])

            credit_entry = sale_item.balance_entries.filter(
                status=CustomerBalanceEntry.Status.OPEN,
                entry_type=CustomerBalanceEntry.EntryType.CREDIT,
            ).order_by("created_at").first()
            if credit_entry is not None:
                if remaining_credit == Decimal("0.00"):
                    credit_entry.status = CustomerBalanceEntry.Status.RESOLVED
                    credit_entry.save(update_fields=["status", "updated_at"])
                else:
                    credit_entry.amount = remaining_credit
                    credit_entry.save(update_fields=["amount", "updated_at"])
        elif not sale_item.is_settled:
            sale_item.payment_status = SaleItem.PaymentStatus.NOW
            sale_item.is_settled = True
            item_fields_to_update.extend(["payment_status", "is_settled"])
        else:
            raise ValidationError({"regularize_amount": "There is no outstanding balance to regularize."})

    still_pending = not sale_item.is_collected or not sale_item.is_settled
    next_priority = sale_item.pending_priority if still_pending else 0
    if sale_item.pending_priority != next_priority:
        sale_item.pending_priority = next_priority
        item_fields_to_update.append("pending_priority")

    if item_fields_to_update:
        sale_item.save(update_fields=[*item_fields_to_update, "updated_at"])

    if sale_item.sale.customer_id:
        rebuild_customer_balances(sale_item.sale.customer)

    rebuild_sale_totals(sale_item.sale)
    return sale_item


@transaction.atomic
def create_sale_from_payload(*, tenant, seller, validated_data):
    items_data = validated_data.pop("items")
    customer_data = validated_data.pop("customer", None)
    store = validated_data["store"]

    if store.tenant_id != tenant.id:
        raise ValidationError({"store": "Selected store does not belong to the active tenant."})

    customer = resolve_customer(tenant, customer_data)
    sale = Sale.objects.create(tenant=tenant, seller=seller, customer=customer, **validated_data)

    next_priority = SaleItem.objects.filter(tenant=tenant).aggregate(value=Max("pending_priority")).get("value") or 0
    gross_total = Decimal("0.00")
    paid_total = Decimal("0.00")
    debt_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    has_pending_items = False

    for item_data in items_data:
        product = item_data["product"]
        quantity_units = item_data["quantity_units"]
        unit_price = item_data.get("unit_price") or product.unit_price
        amount_paid = item_data.get("amount_paid", Decimal("0.00"))
        pickup_status = item_data.get("pickup_status", SaleItem.PickupStatus.NOW)
        payment_status = item_data.get("payment_status") or SaleItem.PaymentStatus.NOW
        note = item_data.get("note", "")
        voice_note = item_data.get("voice_note")

        inventory = (
            Inventory.objects.select_for_update()
            .filter(tenant=tenant, store=store, product=product, is_active=True)
            .first()
        )
        if inventory is None:
            raise ValidationError(
                {"items": f"{product.name} is not stocked in {store.name}."}
            )
        if inventory.stock_units < quantity_units:
            raise ValidationError({"items": f"Insufficient stock for {product.name}."})

        line_total = unit_price * quantity_units
        requires_customer = pickup_status == SaleItem.PickupStatus.LATER or amount_paid != line_total
        if requires_customer and customer is None:
            raise ValidationError(
                {"customer": "A customer must be selected or created for debt, credit, or pickup-later items."}
            )

        inventory.stock_units -= quantity_units
        inventory.save(update_fields=["stock_units", "updated_at"])
        allocate_stock_batches(inventory, quantity_units)
        StockMovement.objects.create(
            tenant=tenant,
            inventory=inventory,
            performed_by=seller,
            movement_type=StockMovement.MovementType.SALE,
            units_delta=-quantity_units,
            note=note,
            unit_price_snapshot=unit_price,
        )

        pending_priority = 0
        is_collected = pickup_status == SaleItem.PickupStatus.NOW
        is_settled = amount_paid == line_total
        if not is_collected or not is_settled:
            next_priority += 1
            pending_priority = next_priority
            has_pending_items = True

        sale_item = SaleItem.objects.create(
            tenant=tenant,
            sale=sale,
            product=product,
            quantity_units=quantity_units,
            unit_price=unit_price,
            line_total=line_total,
            amount_paid=amount_paid,
            pickup_status=pickup_status,
            payment_status=payment_status,
            note=note,
            voice_note=voice_note,
            pending_priority=pending_priority,
            is_collected=is_collected,
            is_settled=is_settled,
        )

        if customer is not None and amount_paid < line_total:
            debt_amount = line_total - amount_paid
            debt_total += debt_amount
            CustomerBalanceEntry.objects.create(
                tenant=tenant,
                customer=customer,
                sale_item=sale_item,
                entry_type=CustomerBalanceEntry.EntryType.DEBT,
                amount=debt_amount,
                note=note,
            )
        elif customer is not None and amount_paid > line_total:
            credit_amount = amount_paid - line_total
            credit_total += credit_amount
            CustomerBalanceEntry.objects.create(
                tenant=tenant,
                customer=customer,
                sale_item=sale_item,
                entry_type=CustomerBalanceEntry.EntryType.CREDIT,
                amount=credit_amount,
                note=note,
            )

        gross_total += line_total
        paid_total += amount_paid

    sale.gross_total = gross_total
    sale.paid_total = paid_total
    sale.debt_total = debt_total
    sale.credit_total = credit_total
    sale.status = Sale.Status.OPEN if has_pending_items else Sale.Status.COMPLETED
    sale.save(update_fields=["gross_total", "paid_total", "debt_total", "credit_total", "status", "updated_at"])

    if customer is not None:
        rebuild_customer_balances(customer)

    return sale
