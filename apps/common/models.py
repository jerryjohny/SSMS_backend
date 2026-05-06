from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedModel(TimeStampedModel):
    tenant = models.ForeignKey("accounts.Tenant", on_delete=models.CASCADE)

    class Meta:
        abstract = True


class AuditEvent(TenantScopedModel):
    class EventType(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        SELL = "sell", "Sell"
        RESTOCK = "restock", "Restock"
        REGULARIZE = "regularize", "Regularize"
        REORDER = "reorder", "Reorder"
        PASSWORD = "password", "Password"
        LOGIN = "login", "Login"

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_name = models.CharField(max_length=180, blank=True)
    actor_role = models.CharField(max_length=40, blank=True)
    store = models.ForeignKey(
        "accounts.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    resource_type = models.CharField(max_length=60)
    resource_id = models.PositiveIntegerField(null=True, blank=True)
    resource_label = models.CharField(max_length=255, blank=True)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_event_type_display()}: {self.summary}"
