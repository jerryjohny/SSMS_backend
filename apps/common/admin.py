from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "summary", "actor_name", "store", "resource_type")
    list_filter = ("event_type", "actor_role", "store", "resource_type")
    search_fields = ("summary", "actor_name", "resource_label", "resource_type")
    ordering = ("-created_at", "-id")
