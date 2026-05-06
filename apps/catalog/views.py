from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.common.audit import create_audit_event, normalize_field_names, resolve_resource_label
from apps.common.permissions import ReadOnlyOrAdminOrSysAdmin
from apps.common.tenancy import TenantScopedViewSetMixin

from .models import Inventory, Product, StockBatch
from .serializers import (
    InventorySerializer,
    ProductRegistrationSerializer,
    ProductSerializer,
    RestockSerializer,
    StockBatchSerializer,
)


class ProductViewSet(TenantScopedViewSetMixin, ModelViewSet):
    permission_classes = [ReadOnlyOrAdminOrSysAdmin]
    queryset = Product.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "barcode", "sku"]
    ordering_fields = ["name", "created_at", "updated_at"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        store_id = self.request.query_params.get("store")

        if store_id:
            queryset = queryset.filter(inventories__store_id=store_id, inventories__is_active=True).distinct()
            queryset = queryset.prefetch_related(
                Prefetch(
                    "inventories",
                    queryset=Inventory.objects.select_related("store", "product").filter(
                        store_id=store_id,
                        is_active=True,
                    ),
                ),
                Prefetch(
                    "stock_batches",
                    queryset=StockBatch.objects.select_related("inventory__store").filter(
                        inventory__store_id=store_id
                    ),
                ),
            )
            return queryset

        return queryset.prefetch_related("inventories", "stock_batches")

    def get_serializer_class(self):
        if self.action == "create":
            return ProductRegistrationSerializer
        return ProductSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant"] = self.get_tenant()
        context["store_id"] = self.request.query_params.get("store")
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        initial_inventory = product.inventories.select_related("store").first()
        create_audit_event(
            tenant=product.tenant,
            actor=request.user,
            store=initial_inventory.store if initial_inventory else None,
            event_type="create",
            resource_type="product",
            resource_id=product.id,
            resource_label=resolve_resource_label(product),
            summary=f"Created product {product.name}.",
            metadata={"fields": normalize_field_names(request.data.keys())},
        )
        response_serializer = ProductSerializer(product, context=self.get_serializer_context())
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        product = serializer.save()
        inventory = product.inventories.select_related("store").first()
        create_audit_event(
            tenant=product.tenant,
            actor=self.request.user,
            store=inventory.store if inventory else None,
            event_type="update",
            resource_type="product",
            resource_id=product.id,
            resource_label=resolve_resource_label(product),
            summary=f"Updated product {product.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_destroy(self, instance):
        tenant = instance.tenant
        inventory = instance.inventories.select_related("store").first()
        product_id = instance.id
        product_name = instance.name
        super().perform_destroy(instance)
        create_audit_event(
            tenant=tenant,
            actor=self.request.user,
            store=inventory.store if inventory else None,
            event_type="delete",
            resource_type="product",
            resource_id=product_id,
            resource_label=product_name,
            summary=f"Deleted product {product_name}.",
        )

    @action(detail=False, methods=["get"], url_path="expiry-alerts")
    def expiry_alerts(self, request):
        tenant = self.get_tenant()
        days = int(request.query_params.get("days", 30))
        store_id = request.query_params.get("store")
        cutoff = timezone.localdate() + timedelta(days=days)
        batches = (
            StockBatch.objects.select_related("product", "inventory__store")
            .filter(tenant=tenant, units_remaining__gt=0, expiry_date__isnull=False, expiry_date__lte=cutoff)
            .order_by("expiry_date")
        )
        if store_id:
            batches = batches.filter(inventory__store_id=store_id)
        serializer = StockBatchSerializer(batches, many=True)
        return Response(serializer.data)


class InventoryViewSet(TenantScopedViewSetMixin, ModelViewSet):
    permission_classes = [ReadOnlyOrAdminOrSysAdmin]
    serializer_class = InventorySerializer
    queryset = Inventory.objects.select_related("product", "store").all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "stock_units", "updated_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        store_id = self.request.query_params.get("store")
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        product_id = self.request.query_params.get("product")
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    def perform_create(self, serializer):
        inventory = serializer.save(tenant=self.get_tenant())
        create_audit_event(
            tenant=inventory.tenant,
            actor=self.request.user,
            store=inventory.store,
            event_type="create",
            resource_type="inventory",
            resource_id=inventory.id,
            resource_label=str(inventory),
            summary=f"Created inventory for {inventory.product.name} in {inventory.store.name}.",
        )

    def perform_update(self, serializer):
        inventory = serializer.save()
        create_audit_event(
            tenant=inventory.tenant,
            actor=self.request.user,
            store=inventory.store,
            event_type="update",
            resource_type="inventory",
            resource_id=inventory.id,
            resource_label=str(inventory),
            summary=f"Updated inventory for {inventory.product.name} in {inventory.store.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_destroy(self, instance):
        tenant = instance.tenant
        store = instance.store
        inventory_id = instance.id
        inventory_label = str(instance)
        super().perform_destroy(instance)
        create_audit_event(
            tenant=tenant,
            actor=self.request.user,
            store=store,
            event_type="delete",
            resource_type="inventory",
            resource_id=inventory_id,
            resource_label=inventory_label,
            summary=f"Deleted inventory {inventory_label}.",
        )

    @action(detail=False, methods=["post"], url_path="restock")
    def restock(self, request):
        serializer = RestockSerializer(
            data=request.data,
            context={"request": request, "tenant": self.get_tenant()},
        )
        serializer.is_valid(raise_exception=True)
        inventory = serializer.save()
        create_audit_event(
            tenant=inventory.tenant,
            actor=request.user,
            store=inventory.store,
            event_type="restock",
            resource_type="inventory",
            resource_id=inventory.id,
            resource_label=str(inventory),
            summary=f"Restocked {inventory.product.name} in {inventory.store.name}.",
            metadata={
                "units_added": request.data.get("units_added"),
                "packages_added": request.data.get("packages_added"),
                "boxes_added": request.data.get("boxes_added"),
                "expiry_date": request.data.get("expiry_date"),
            },
        )
        return Response(InventorySerializer(inventory).data, status=status.HTTP_200_OK)
