from decimal import Decimal

from django.db import models
from django.db.models import Min, Sum

from apps.common.models import TenantScopedModel


class Product(TenantScopedModel):
    name = models.CharField(max_length=180)
    barcode = models.CharField(max_length=80)
    sku = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    packaging_details = models.CharField(max_length=180, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    package_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    box_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    units_per_package = models.PositiveIntegerField(default=1)
    units_per_box = models.PositiveIntegerField(default=1)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "barcode"], name="unique_product_barcode_per_tenant"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def total_stock_units(self) -> int:
        total = self.inventories.aggregate(total=Sum("stock_units")).get("total")
        return total or 0

    @property
    def nearest_expiry_date(self):
        return self.stock_batches.filter(units_remaining__gt=0).aggregate(nearest=Min("expiry_date")).get("nearest")


class Inventory(TenantScopedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventories")
    store = models.ForeignKey("accounts.Store", on_delete=models.CASCADE, related_name="inventories")
    stock_units = models.PositiveIntegerField(default=0)
    reserved_units = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product__name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "product", "store"], name="unique_inventory_per_store_product"),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} @ {self.store.name}"

    @property
    def available_units(self) -> int:
        return max(self.stock_units - self.reserved_units, 0)


class StockBatch(TenantScopedModel):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="batches")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_batches")
    units_received = models.PositiveIntegerField(default=0)
    units_remaining = models.PositiveIntegerField(default=0)
    packages_received = models.PositiveIntegerField(default=0)
    boxes_received = models.PositiveIntegerField(default=0)
    expiry_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["expiry_date", "created_at"]

    def __str__(self) -> str:
        expiry = self.expiry_date.isoformat() if self.expiry_date else "no-expiry"
        return f"{self.product.name} batch ({expiry})"


class StockMovement(TenantScopedModel):
    class MovementType(models.TextChoices):
        REGISTER = "register", "Register"
        RESTOCK = "restock", "Restock"
        SALE = "sale", "Sale"
        ADJUSTMENT = "adjustment", "Adjustment"

    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name="movements")
    batch = models.ForeignKey(StockBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements")
    performed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    units_delta = models.IntegerField()
    note = models.TextField(blank=True)
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.movement_type}: {self.units_delta}"
