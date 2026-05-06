from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Store, Tenant, User


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "tenant", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name", "code")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "tenant",
        "store",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter = ("tenant", "role", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name", "phone")
    ordering = ("username",)
    filter_horizontal = ("groups", "user_permissions", "assigned_stores")
    readonly_fields = ("google_subject", "last_login", "date_joined")

    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "SSMS Access",
            {
                "fields": (
                    "tenant",
                    "store",
                    "assigned_stores",
                    "role",
                    "phone",
                    "google_subject",
                )
            },
        ),
    )

    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "SSMS Access",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "tenant",
                    "store",
                    "assigned_stores",
                    "role",
                    "phone",
                ),
            },
        ),
    )
