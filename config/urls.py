from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views import GoogleAuthView, LoginView, SessionView, StoreViewSet, TenantViewSet, UserViewSet
from apps.catalog.views import InventoryViewSet, ProductViewSet
from apps.common.views import AuditEventViewSet, HealthCheckView
from apps.customers.views import CustomerViewSet
from apps.sales.views import PendingSaleItemViewSet, SaleViewSet


router = DefaultRouter()
router.register("accounts/tenants", TenantViewSet, basename="tenant")
router.register("accounts/stores", StoreViewSet, basename="store")
router.register("accounts/users", UserViewSet, basename="user")
router.register("catalog/products", ProductViewSet, basename="product")
router.register("catalog/inventories", InventoryViewSet, basename="inventory")
router.register("customers", CustomerViewSet, basename="customer")
router.register("sales", SaleViewSet, basename="sale")
router.register("pending-items", PendingSaleItemViewSet, basename="pending-item")
router.register("audit-events", AuditEventViewSet, basename="audit-event")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/v1/auth/login/", LoginView.as_view(), name="auth-login"),
    path("api/v1/auth/google/", GoogleAuthView.as_view(), name="auth-google"),
    path("api/v1/auth/me/", SessionView.as_view(), name="auth-session"),
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("api/v1/", include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
