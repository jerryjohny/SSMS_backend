from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "reference", "phone", "credit_balance", "debt_balance")
    list_filter = ("tenant",)
    search_fields = ("name", "reference", "phone")
