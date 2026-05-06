from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import Tenant


def resolve_tenant_from_request(request):
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False) and getattr(user, "tenant_id", None):
        return user.tenant

    if getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False):
        tenant_slug = request.headers.get("X-Tenant-Slug")
        if tenant_slug:
            return Tenant.objects.filter(slug=tenant_slug, is_active=True).first()

        active_tenants = list(Tenant.objects.filter(is_active=True).order_by("id")[:2])
        if len(active_tenants) == 1:
            return active_tenants[0]

    tenant_slug = request.headers.get("X-Tenant-Slug")
    if tenant_slug:
        return Tenant.objects.filter(slug=tenant_slug, is_active=True).first()

    return None


class TenantScopedViewSetMixin:
    def get_tenant(self):
        tenant = resolve_tenant_from_request(self.request)
        if tenant is None:
            raise PermissionDenied("An authenticated tenant context is required.")
        return tenant

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = resolve_tenant_from_request(self.request)
        if tenant is None:
            return queryset.none()
        return queryset.filter(tenant=tenant)
