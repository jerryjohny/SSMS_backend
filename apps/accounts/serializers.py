from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.tenancy import resolve_default_superuser_tenant

from .models import Store, Tenant

User = get_user_model()


def resolve_session_tenant(user) -> Tenant | None:
    if getattr(user, "tenant_id", None):
        return user.tenant

    if getattr(user, "is_superuser", False):
        return resolve_default_superuser_tenant()

    return None


def resolve_session_stores(user) -> list[Store]:
    if getattr(user, "is_superuser", False) and not getattr(user, "tenant_id", None):
        tenant = resolve_session_tenant(user)
        if tenant is None:
            return []
        return list(Store.objects.filter(tenant=tenant, is_active=True).order_by("name"))

    return list(user.accessible_stores)


def resolve_session_primary_store(user) -> Store | None:
    if getattr(user, "is_superuser", False) and not getattr(user, "tenant_id", None):
        stores = resolve_session_stores(user)
        return stores[0] if stores else None

    return getattr(user, "store", None)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class StoreSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "code"]


class StoreAdminSummarySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "display_name", "email", "phone"]


class StoreSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    admin_user = serializers.SerializerMethodField(read_only=True)
    admin_user_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "tenant",
            "tenant_name",
            "name",
            "code",
            "address",
            "phone",
            "admin_user",
            "admin_user_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "tenant_name", "created_at", "updated_at"]

    def get_admin_user(self, obj):
        admin_user = (
            User.objects.filter(
                tenant=obj.tenant,
                role=User.Role.ADMIN,
                store=obj,
                is_active=True,
            )
            .order_by("first_name", "last_name", "username")
            .first()
        )
        if admin_user is None:
            return None
        return StoreAdminSummarySerializer(admin_user).data

    def validate(self, attrs):
        tenant = self.context.get("tenant") or getattr(self.instance, "tenant", None)
        admin_user_id = attrs.get("admin_user_id", serializers.empty)

        if admin_user_id is not serializers.empty:
            if admin_user_id is None:
                attrs["_resolved_admin_user"] = None
            else:
                admin_user = (
                    User.objects.select_related("tenant", "store")
                    .prefetch_related("assigned_stores")
                    .filter(
                        pk=admin_user_id,
                        tenant=tenant,
                        role=User.Role.ADMIN,
                        is_active=True,
                    )
                    .first()
                )
                if admin_user is None:
                    raise serializers.ValidationError(
                        {"admin_user_id": "Select an active tenant admin for this shop."}
                    )
                attrs["_resolved_admin_user"] = admin_user

        return attrs

    def _apply_admin_assignment(self, store: Store, admin_user):
        current_admins = list(
            User.objects.filter(
                tenant=store.tenant,
                role=User.Role.ADMIN,
                store=store,
            ).exclude(pk=getattr(admin_user, "pk", None))
        )

        for current_admin in current_admins:
            current_admin.store = None
            current_admin.save(update_fields=["store", "updated_at"])

        if admin_user is None:
            return

        if admin_user.store_id != store.id:
            admin_user.store = store
            admin_user.save(update_fields=["store", "updated_at"])

        admin_user.assigned_stores.add(store)

    def create(self, validated_data):
        admin_user = validated_data.pop("_resolved_admin_user", serializers.empty)
        validated_data.pop("admin_user_id", None)
        store = super().create(validated_data)

        if admin_user is not serializers.empty:
            self._apply_admin_assignment(store, admin_user)

        return store

    def update(self, instance, validated_data):
        admin_user = validated_data.pop("_resolved_admin_user", serializers.empty)
        validated_data.pop("admin_user_id", None)
        store = super().update(instance, validated_data)

        if admin_user is not serializers.empty:
            self._apply_admin_assignment(store, admin_user)

        return store


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    assigned_stores = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.select_related("tenant").all(),
        many=True,
        required=False,
    )
    assigned_store_details = serializers.SerializerMethodField()
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    display_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "tenant",
            "tenant_name",
            "store",
            "assigned_stores",
            "assigned_store_details",
            "role",
            "is_active",
            "password",
        ]
        read_only_fields = ["tenant", "tenant_name"]

    def get_assigned_store_details(self, obj):
        return StoreSummarySerializer(obj.accessible_stores, many=True).data

    def validate(self, attrs):
        tenant = self.context.get("tenant") or getattr(self.instance, "tenant", None)
        assigned_stores = attrs.get("assigned_stores")
        primary_store = attrs.get("store")

        if primary_store and tenant and primary_store.tenant_id != tenant.id:
            raise serializers.ValidationError({"store": "Selected store does not belong to the active tenant."})

        if assigned_stores is not None and tenant:
            invalid_store = next((store for store in assigned_stores if store.tenant_id != tenant.id), None)
            if invalid_store is not None:
                raise serializers.ValidationError(
                    {"assigned_stores": "All assigned shops must belong to the active tenant."}
                )

        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "A password is required when creating a user."})

        return attrs

    def create(self, validated_data):
        assigned_stores = validated_data.pop("assigned_stores", [])
        password = validated_data.pop("password", None)
        display_name = validated_data.pop("display_name", "").strip()
        tenant = self.context["tenant"]

        if display_name and not validated_data.get("first_name") and not validated_data.get("last_name"):
            first_name, _, last_name = display_name.partition(" ")
            validated_data["first_name"] = first_name
            validated_data["last_name"] = last_name

        user = User(tenant=tenant, **validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        if assigned_stores:
            user.assigned_stores.set(assigned_stores)
        return user

    def update(self, instance, validated_data):
        assigned_stores = validated_data.pop("assigned_stores", None)
        password = validated_data.pop("password", None)
        display_name = validated_data.pop("display_name", "").strip()

        if display_name and "first_name" not in validated_data and "last_name" not in validated_data:
            first_name, _, last_name = display_name.partition(" ")
            validated_data["first_name"] = first_name
            validated_data["last_name"] = last_name

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if password:
            instance.set_password(password)

        instance.save()

        if assigned_stores is not None:
            instance.assigned_stores.set(assigned_stores)

        return instance


class SessionUserSerializer(serializers.ModelSerializer):
    tenant = serializers.SerializerMethodField()
    store = serializers.SerializerMethodField()
    assigned_stores = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "tenant",
            "store",
            "assigned_stores",
            "is_active",
        ]

    def get_tenant(self, obj):
        tenant = resolve_session_tenant(obj)
        if tenant is None:
            return None
        return TenantSerializer(tenant).data

    def get_store(self, obj):
        store = resolve_session_primary_store(obj)
        if store is None:
            return None
        return StoreSummarySerializer(store).data

    def get_assigned_stores(self, obj):
        return StoreSummarySerializer(resolve_session_stores(obj), many=True).data


class SessionProfileSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    confirm_new_password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "display_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "current_password",
            "new_password",
            "confirm_new_password",
        ]

    def validate(self, attrs):
        current_password = attrs.get("current_password", "")
        new_password = attrs.get("new_password", "")
        confirm_new_password = attrs.get("confirm_new_password", "")
        password_change_requested = any([current_password, new_password, confirm_new_password])

        if not password_change_requested:
            return attrs

        errors: dict[str, list[str] | str] = {}

        if not new_password:
            errors["new_password"] = "Enter a new password."

        if not confirm_new_password:
            errors["confirm_new_password"] = "Confirm the new password."

        if new_password and confirm_new_password and new_password != confirm_new_password:
            errors["confirm_new_password"] = "The new passwords do not match."

        if self.instance and self.instance.has_usable_password():
            if not current_password:
                errors["current_password"] = "Enter your current password."
            elif not self.instance.check_password(current_password):
                errors["current_password"] = "The current password is incorrect."

        if new_password:
            try:
                validate_password(new_password, self.instance)
            except DjangoValidationError as exc:
                errors["new_password"] = list(exc.messages)

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def update(self, instance, validated_data):
        display_name = validated_data.pop("display_name", "").strip()
        validated_data.pop("current_password", "")
        validated_data.pop("confirm_new_password", "")
        new_password = validated_data.pop("new_password", "")
        if display_name and "first_name" not in validated_data and "last_name" not in validated_data:
            first_name, _, last_name = display_name.partition(" ")
            validated_data["first_name"] = first_name
            validated_data["last_name"] = last_name

        for field, value in validated_data.items():
            setattr(instance, field, value)

        update_fields = [*validated_data.keys(), "updated_at"]

        if new_password:
            instance.set_password(new_password)
            update_fields.append("password")

        instance.save(update_fields=list(dict.fromkeys(update_fields)))
        return instance


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        identifier = attrs["identifier"].strip()
        password = attrs["password"]
        user = (
            User.objects.select_related("tenant", "store")
            .prefetch_related("assigned_stores")
            .filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
            .first()
        )

        if user is None or not user.check_password(password):
            raise serializers.ValidationError({"detail": "Invalid credentials."})

        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is disabled."})

        attrs["user"] = user
        return attrs


class GoogleAuthSerializer(serializers.Serializer):
    credential = serializers.CharField()


def build_token_response(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": SessionUserSerializer(user).data,
    }
