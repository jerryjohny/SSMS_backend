from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "event_type",
            "actor_name",
            "actor_role",
            "store",
            "store_name",
            "resource_type",
            "resource_id",
            "resource_label",
            "summary",
            "metadata",
        ]
