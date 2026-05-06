from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.common.audit import create_audit_event, normalize_field_names, resolve_resource_label
from apps.common.tenancy import TenantScopedViewSetMixin

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(TenantScopedViewSetMixin, ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    queryset = Customer.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "reference", "phone"]
    ordering_fields = ["name", "created_at", "debt_balance", "credit_balance"]
    ordering = ["name"]

    def perform_create(self, serializer):
        customer = serializer.save(tenant=self.get_tenant())
        create_audit_event(
            tenant=customer.tenant,
            actor=self.request.user,
            event_type="create",
            resource_type="customer",
            resource_id=customer.id,
            resource_label=resolve_resource_label(customer),
            summary=f"Created customer {customer.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_update(self, serializer):
        customer = serializer.save()
        create_audit_event(
            tenant=customer.tenant,
            actor=self.request.user,
            event_type="update",
            resource_type="customer",
            resource_id=customer.id,
            resource_label=resolve_resource_label(customer),
            summary=f"Updated customer {customer.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_destroy(self, instance):
        tenant = instance.tenant
        customer_id = instance.id
        customer_name = instance.name
        super().perform_destroy(instance)
        create_audit_event(
            tenant=tenant,
            actor=self.request.user,
            event_type="delete",
            resource_type="customer",
            resource_id=customer_id,
            resource_label=customer_name,
            summary=f"Deleted customer {customer_name}.",
        )
