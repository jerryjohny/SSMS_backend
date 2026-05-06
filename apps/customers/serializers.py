from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "tenant",
            "name",
            "reference",
            "phone",
            "notes",
            "credit_balance",
            "debt_balance",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "credit_balance", "debt_balance", "created_at", "updated_at"]
