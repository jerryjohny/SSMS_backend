from django.contrib import admin

from .models import Inventory, Product, StockBatch, StockMovement


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "tenant", "unit_price", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("name", "barcode", "sku")


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ("product", "store", "stock_units", "reserved_units", "is_active")
    list_filter = ("tenant", "store", "is_active")
    search_fields = ("product__name", "product__barcode")


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ("product", "inventory", "units_remaining", "expiry_date")
    list_filter = ("tenant", "inventory__store", "expiry_date")
    search_fields = ("product__name", "product__barcode")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("inventory", "movement_type", "units_delta", "performed_by", "created_at")
    list_filter = ("tenant", "movement_type")
    search_fields = ("inventory__product__name", "inventory__product__barcode")
