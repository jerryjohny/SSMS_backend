from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.common.models import TenantScopedModel, TimeStampedModel


class Tenant(TimeStampedModel):
    name = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Store(TenantScopedModel):
    name = models.CharField(max_length=180)
    code = models.CharField(max_length=50)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_store_code_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant.slug})"


class User(AbstractUser, TimeStampedModel):
    class Role(models.TextChoices):
        SYSADMIN = "sysadmin", "SysAdmin"
        ADMIN = "admin", "Admin"
        SELLER = "seller", "Seller"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    assigned_stores = models.ManyToManyField(
        Store,
        blank=True,
        related_name="assigned_users",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SELLER)
    phone = models.CharField(max_length=40, blank=True)
    google_subject = models.CharField(max_length=255, blank=True, null=True, unique=True)

    @property
    def display_name(self) -> str:
        full_name = self.get_full_name().strip()
        return full_name or self.username

    @property
    def accessible_stores(self):
        assigned = list(self.assigned_stores.filter(is_active=True).order_by("name"))
        if self.store_id and all(store.pk != self.store_id for store in assigned):
            assigned.insert(0, self.store)
        return assigned

    def __str__(self) -> str:
        return self.display_name
