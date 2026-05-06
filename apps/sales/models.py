from decimal import Decimal
import uuid

from django.db import models

from apps.common.models import TenantScopedModel


def order_number_default() -> str:
    return uuid.uuid4().hex[:12].upper()


class Sale(TenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    order_number = models.CharField(max_length=20, unique=True, default=order_number_default, editable=False)
    store = models.ForeignKey("accounts.Store", on_delete=models.PROTECT, related_name="sales")
    seller = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    note = models.TextField(blank=True)
    gross_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    paid_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    debt_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.order_number


class SaleItem(TenantScopedModel):
    class PickupStatus(models.TextChoices):
        NOW = "now", "Now"
        LATER = "later", "Later"

    class PaymentStatus(models.TextChoices):
        NOW = "now", "Now"
        PARTIAL = "partial", "Partial"
        LATER = "later", "Later"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="sale_items")
    quantity_units = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    pickup_status = models.CharField(max_length=20, choices=PickupStatus.choices, default=PickupStatus.NOW)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.NOW)
    note = models.TextField(blank=True)
    voice_note = models.FileField(upload_to="voice-notes/", null=True, blank=True)
    pending_priority = models.PositiveIntegerField(default=0)
    is_collected = models.BooleanField(default=True)
    is_settled = models.BooleanField(default=True)

    class Meta:
        ordering = ["pending_priority", "-created_at"]

    def __str__(self) -> str:
        return f"{self.product.name} x {self.quantity_units}"

    @property
    def debt_amount(self) -> Decimal:
        return max(self.line_total - self.amount_paid, Decimal("0.00"))

    @property
    def credit_amount(self) -> Decimal:
        return max(self.amount_paid - self.line_total, Decimal("0.00"))

    @property
    def is_pending(self) -> bool:
        return not self.is_collected or not self.is_settled or self.pending_priority > 0


class CustomerBalanceEntry(TenantScopedModel):
    class EntryType(models.TextChoices):
        DEBT = "debt", "Debt"
        CREDIT = "credit", "Credit"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="balance_entries")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="balance_entries")
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.amount}"
