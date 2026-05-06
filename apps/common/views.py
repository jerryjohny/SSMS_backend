from django.db import models
from django.utils.dateparse import parse_date
from rest_framework import filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.common.permissions import IsTenantSysAdmin
from apps.common.tenancy import TenantScopedViewSetMixin

from .models import AuditEvent
from .serializers import AuditEventSerializer


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "ssms-backend"})


class AuditEventViewSet(TenantScopedViewSetMixin, ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, IsTenantSysAdmin]
    queryset = AuditEvent.objects.select_related("actor", "store").all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "event_type", "resource_type"]
    ordering = ["-created_at", "-id"]
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()

        event_type = self.request.query_params.get("event_type", "").strip()
        if event_type:
            queryset = queryset.filter(event_type=event_type)

        raw_date = self.request.query_params.get("date", "").strip()
        if raw_date:
            target_date = parse_date(raw_date)
            if target_date is None:
                return queryset.none()
            queryset = queryset.filter(created_at__date=target_date)

        store_id = self.request.query_params.get("store", "").strip()
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                models.Q(summary__icontains=search)
                | models.Q(actor_name__icontains=search)
                | models.Q(resource_label__icontains=search)
                | models.Q(resource_type__icontains=search)
            )

        return queryset
