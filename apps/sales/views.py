from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.accounts.models import Store
from apps.common.audit import create_audit_event, resolve_resource_label
from apps.common.permissions import IsTenantAdminOrSysAdmin
from apps.common.tenancy import TenantScopedViewSetMixin

from .models import Sale, SaleItem
from .serializers import (
    PendingRegularizeSerializer,
    PendingSaleItemSerializer,
    SaleCreateSerializer,
    SaleSerializer,
)
from .services import regularize_pending_item


def decimal_text(value):
    return f"{(value or Decimal('0.00')):.2f}"


class SaleViewSet(TenantScopedViewSetMixin, ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Sale.objects.select_related("store", "seller", "customer").prefetch_related("items__balance_entries").all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "gross_total", "paid_total"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        return SaleSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant"] = self.get_tenant()
        return context

    def perform_create(self, serializer):
        sale = serializer.save()
        create_audit_event(
            tenant=sale.tenant,
            actor=self.request.user,
            store=sale.store,
            event_type="sell",
            resource_type="sale",
            resource_id=sale.id,
            resource_label=resolve_resource_label(sale),
            summary=f"Recorded sale {sale.order_number}.",
            metadata={
                "item_count": sale.items.count(),
                "gross_total": sale.gross_total,
                "paid_total": sale.paid_total,
                "debt_total": sale.debt_total,
                "credit_total": sale.credit_total,
                "customer": sale.customer.name if sale.customer_id else "",
            },
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="accounting",
        permission_classes=[IsAuthenticated, IsTenantAdminOrSysAdmin],
    )
    def accounting(self, request):
        tenant = self.get_tenant()
        raw_date = request.query_params.get("date", "").strip()
        target_date = parse_date(raw_date) if raw_date else timezone.localdate()

        if raw_date and target_date is None:
            return Response({"detail": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(created_at__date=target_date)
        store = None
        store_id = request.query_params.get("store")

        if store_id:
            try:
                store = Store.objects.get(pk=store_id, tenant=tenant)
            except Store.DoesNotExist:
                return Response(
                    {"detail": "Selected store does not belong to the active tenant."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(store=store)

        sales = list(queryset.order_by("-created_at"))
        sales_serializer = SaleSerializer(sales, many=True, context=self.get_serializer_context())
        item_queryset = SaleItem.objects.filter(sale__in=sales)

        sale_summary = queryset.aggregate(
            sale_count=Count("id"),
            gross_total=Sum("gross_total"),
            paid_total=Sum("paid_total"),
            debt_total=Sum("debt_total"),
            credit_total=Sum("credit_total"),
        )
        item_summary = item_queryset.aggregate(
            line_count=Count("id"),
            units_sold=Sum("quantity_units"),
        )

        seller_units = {
            row["sale__seller_id"]: row["units_sold"] or 0
            for row in item_queryset.values("sale__seller_id").annotate(units_sold=Sum("quantity_units"))
        }
        seller_rows = (
            queryset.values("seller_id", "seller__username", "seller__first_name", "seller__last_name")
            .annotate(
                sale_count=Count("id"),
                gross_total=Sum("gross_total"),
                paid_total=Sum("paid_total"),
                debt_total=Sum("debt_total"),
                credit_total=Sum("credit_total"),
            )
            .order_by("-gross_total", "seller__username")
        )

        sellers = []
        for row in seller_rows:
            first_name = (row.get("seller__first_name") or "").strip()
            last_name = (row.get("seller__last_name") or "").strip()
            full_name = " ".join(part for part in [first_name, last_name] if part).strip()

            sellers.append(
                {
                    "seller_id": row["seller_id"],
                    "seller_name": full_name or row["seller__username"],
                    "sale_count": row["sale_count"],
                    "units_sold": seller_units.get(row["seller_id"], 0),
                    "gross_total": decimal_text(row.get("gross_total")),
                    "paid_total": decimal_text(row.get("paid_total")),
                    "debt_total": decimal_text(row.get("debt_total")),
                    "credit_total": decimal_text(row.get("credit_total")),
                }
            )

        return Response(
            {
                "date": target_date.isoformat(),
                "store_id": store.id if store else None,
                "store_name": store.name if store else None,
                "summary": {
                    "sale_count": sale_summary.get("sale_count") or 0,
                    "line_count": item_summary.get("line_count") or 0,
                    "units_sold": item_summary.get("units_sold") or 0,
                    "gross_total": decimal_text(sale_summary.get("gross_total")),
                    "paid_total": decimal_text(sale_summary.get("paid_total")),
                    "debt_total": decimal_text(sale_summary.get("debt_total")),
                    "credit_total": decimal_text(sale_summary.get("credit_total")),
                },
                "sellers": sellers,
                "sales": sales_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class PendingSaleItemViewSet(TenantScopedViewSetMixin, ReadOnlyModelViewSet):
    serializer_class = PendingSaleItemSerializer
    permission_classes = [IsAuthenticated]
    queryset = SaleItem.objects.select_related("sale__customer", "sale__store", "product").all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["pending_priority", "created_at"]
    ordering = ["pending_priority", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(pending_priority__gt=0)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request):
        if not IsTenantAdminOrSysAdmin().has_permission(request, self):
            return Response({"detail": "Only admins and sysadmins can reorder pending items."}, status=status.HTTP_403_FORBIDDEN)
        tenant = self.get_tenant()
        items = request.data.get("items", [])
        for entry in items:
            SaleItem.objects.filter(tenant=tenant, pk=entry["id"]).update(pending_priority=entry["pending_priority"])
        create_audit_event(
            tenant=tenant,
            actor=request.user,
            event_type="reorder",
            resource_type="pending_queue",
            summary="Reordered pending items.",
            metadata={"item_count": len(items)},
        )
        return Response({"status": "reordered"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="regularize")
    def regularize(self, request, pk=None):
        tenant = self.get_tenant()
        sale_item = (
            SaleItem.objects.select_related("sale__customer", "sale__store", "product")
            .prefetch_related("sale__items", "balance_entries")
            .filter(tenant=tenant, pk=pk)
            .first()
        )
        if sale_item is None:
            return Response({"detail": "Pending item not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PendingRegularizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_item = regularize_pending_item(
            tenant=tenant,
            sale_item=sale_item,
            **serializer.validated_data,
        )
        create_audit_event(
            tenant=tenant,
            actor=request.user,
            store=updated_item.sale.store,
            event_type="regularize",
            resource_type="pending_item",
            resource_id=updated_item.id,
            resource_label=updated_item.product.name,
            summary=f"Regularized pending item for {updated_item.product.name}.",
            metadata={
                "sale_order_number": updated_item.sale.order_number,
                "mark_collected": serializer.validated_data.get("mark_collected", False),
                "regularize_amount": serializer.validated_data.get("regularize_amount"),
            },
        )
        return Response(PendingSaleItemSerializer(updated_item).data, status=status.HTTP_200_OK)
