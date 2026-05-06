from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from apps.common.audit import create_audit_event, normalize_field_names, resolve_resource_label
from apps.common.permissions import IsTenantSysAdmin, ReadOnlyOrSysAdmin
from apps.common.tenancy import TenantScopedViewSetMixin, resolve_tenant_from_request

from .models import Store, Tenant, User
from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    SessionProfileSerializer,
    SessionUserSerializer,
    StoreSerializer,
    TenantSerializer,
    UserSerializer,
    build_token_response,
)


def verify_google_identity(credential: str) -> dict:
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise ValidationError(
            {"detail": "Google OAuth support is not installed on the backend yet."}
        ) from exc

    allowed_client_ids = [
        client_id.strip()
        for client_id in getattr(settings, "GOOGLE_OAUTH_CLIENT_IDS", [])
        if client_id.strip()
    ]

    if not allowed_client_ids:
        raise ValidationError({"detail": "Google OAuth is not configured on the backend."})

    payload = id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        audience=None,
    )

    if payload.get("aud") not in allowed_client_ids:
        raise ValidationError({"detail": "This Google token was issued for a different client."})

    if not payload.get("email_verified"):
        raise ValidationError({"detail": "The Google account email is not verified."})

    return payload


def resolve_google_user(identity: dict) -> User:
    queryset = User.objects.select_related("tenant", "store").prefetch_related("assigned_stores")
    subject = identity.get("sub", "").strip()
    email = identity.get("email", "").strip()
    user = queryset.filter(google_subject=subject).first() if subject else None

    if user is None and email:
        matches = list(queryset.filter(email__iexact=email)[:2])
        if len(matches) > 1:
            raise ValidationError(
                {"detail": "Multiple users share this email. Ask a sysadmin to resolve the account mapping."}
            )
        user = matches[0] if matches else None

    if user is None:
        raise ValidationError({"detail": "No SSMS user is linked to this Google account yet."})

    if not user.is_active:
        raise ValidationError({"detail": "This account is disabled."})

    updated_fields = []
    if subject and user.google_subject != subject:
        user.google_subject = subject
        updated_fields.append("google_subject")
    if identity.get("given_name") and not user.first_name:
        user.first_name = identity["given_name"]
        updated_fields.append("first_name")
    if identity.get("family_name") and not user.last_name:
        user.last_name = identity["family_name"]
        updated_fields.append("last_name")
    if email and not user.email:
        user.email = email
        updated_fields.append("email")

    if updated_fields:
        user.save(update_fields=[*updated_fields, "updated_at"])

    return user


class TenantViewSet(ModelViewSet):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]
    queryset = Tenant.objects.all()

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Tenant.objects.all()
        tenant = resolve_tenant_from_request(self.request)
        if tenant is None:
            return Tenant.objects.none()
        return Tenant.objects.filter(pk=tenant.pk)

    def create(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Only Django superusers can create tenants.")
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Only Django superusers can update tenants.")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Only Django superusers can update tenants.")
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Only Django superusers can delete tenants.")
        return super().destroy(request, *args, **kwargs)


class StoreViewSet(TenantScopedViewSetMixin, ModelViewSet):
    serializer_class = StoreSerializer
    queryset = Store.objects.select_related("tenant").all()

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsTenantSysAdmin()]
        return [IsAuthenticated()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant"] = self.get_tenant()
        return context

    def perform_create(self, serializer):
        store = serializer.save(tenant=self.get_tenant())
        create_audit_event(
            tenant=store.tenant,
            actor=self.request.user,
            store=store,
            event_type="create",
            resource_type="store",
            resource_id=store.id,
            resource_label=resolve_resource_label(store),
            summary=f"Created shop {store.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_update(self, serializer):
        store = serializer.save()
        create_audit_event(
            tenant=store.tenant,
            actor=self.request.user,
            store=store,
            event_type="update",
            resource_type="store",
            resource_id=store.id,
            resource_label=resolve_resource_label(store),
            summary=f"Updated shop {store.name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_destroy(self, instance):
        store_name = instance.name
        tenant = instance.tenant
        store_id = instance.id
        super().perform_destroy(instance)
        create_audit_event(
            tenant=tenant,
            actor=self.request.user,
            event_type="delete",
            resource_type="store",
            resource_id=store_id,
            resource_label=store_name,
            summary=f"Deleted shop {store_name}.",
        )


class UserViewSet(TenantScopedViewSetMixin, ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsTenantSysAdmin]
    queryset = User.objects.select_related("tenant", "store").prefetch_related("assigned_stores").all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant"] = self.get_tenant()
        return context

    def perform_create(self, serializer):
        user = serializer.save()
        create_audit_event(
            tenant=user.tenant,
            actor=self.request.user,
            store=user.store,
            event_type="create",
            resource_type="user",
            resource_id=user.id,
            resource_label=resolve_resource_label(user),
            summary=f"Created user {user.display_name}.",
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_update(self, serializer):
        user = serializer.save()
        event_type = "password" if "password" in self.request.data else "update"
        summary = (
            f"Changed password for {user.display_name}."
            if event_type == "password"
            else f"Updated user {user.display_name}."
        )
        create_audit_event(
            tenant=user.tenant,
            actor=self.request.user,
            store=user.store,
            event_type=event_type,
            resource_type="user",
            resource_id=user.id,
            resource_label=resolve_resource_label(user),
            summary=summary,
            metadata={"fields": normalize_field_names(self.request.data.keys())},
        )

    def perform_destroy(self, instance):
        tenant = instance.tenant
        store = instance.store
        user_id = instance.id
        user_label = instance.display_name
        super().perform_destroy(instance)
        create_audit_event(
            tenant=tenant,
            actor=self.request.user,
            store=store,
            event_type="delete",
            resource_type="user",
            resource_id=user_id,
            resource_label=user_label,
            summary=f"Deleted user {user_label}.",
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        if user.tenant_id:
            create_audit_event(
                tenant=user.tenant,
                actor=user,
                store=user.store,
                event_type="login",
                resource_type="session",
                resource_id=user.id,
                resource_label=resolve_resource_label(user),
                summary=f"{user.display_name} signed in.",
            )
        return Response(build_token_response(user), status=status.HTTP_200_OK)


class GoogleAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity = verify_google_identity(serializer.validated_data["credential"])
        user = resolve_google_user(identity)
        if user.tenant_id:
            create_audit_event(
                tenant=user.tenant,
                actor=user,
                store=user.store,
                event_type="login",
                resource_type="session",
                resource_id=user.id,
                resource_label=resolve_resource_label(user),
                summary=f"{user.display_name} signed in with Google.",
            )
        return Response(build_token_response(user), status=status.HTTP_200_OK)


class SessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = SessionUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = SessionProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        tenant = resolve_tenant_from_request(request)
        if tenant is not None:
            event_type = "password" if request.data.get("new_password") else "update"
            summary = (
                f"{request.user.display_name} changed the profile password."
                if event_type == "password"
                else f"{request.user.display_name} updated the profile."
            )
            create_audit_event(
                tenant=tenant,
                actor=request.user,
                store=getattr(request.user, "store", None),
                event_type=event_type,
                resource_type="profile",
                resource_id=request.user.id,
                resource_label=resolve_resource_label(request.user),
                summary=summary,
                metadata={"fields": normalize_field_names(request.data.keys())},
            )
        return Response(SessionUserSerializer(request.user).data, status=status.HTTP_200_OK)
