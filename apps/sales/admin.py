from django.contrib import admin

from .models import CustomerBalanceEntry, Sale, SaleItem


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("order_number", "tenant", "store", "seller", "status", "gross_total", "paid_total")
    list_filter = ("tenant", "store", "status")
    search_fields = ("order_number", "customer__name", "seller__username")


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ("sale", "product", "quantity_units", "line_total", "amount_paid", "pickup_status", "payment_status")
    list_filter = ("tenant", "pickup_status", "payment_status", "is_collected", "is_settled")
    search_fields = ("sale__order_number", "product__name")


@admin.register(CustomerBalanceEntry)
class CustomerBalanceEntryAdmin(admin.ModelAdmin):
    list_display = ("customer", "entry_type", "amount", "status", "created_at")
    list_filter = ("tenant", "entry_type", "status")
    search_fields = ("customer__name", "sale_item__sale__order_number")
