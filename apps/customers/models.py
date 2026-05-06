from django.db import models

from apps.common.models import TenantScopedModel


class Customer(TenantScopedModel):
    name = models.CharField(max_length=180)
    reference = models.CharField(max_length=120)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    debt_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="unique_customer_reference_per_tenant"),
        ]

    def __str__(self) -> str:
        return self.name
