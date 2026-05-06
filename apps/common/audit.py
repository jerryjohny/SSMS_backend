from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import AuditEvent


SENSITIVE_FIELD_NAMES = {
    "password",
    "current_password",
    "new_password",
    "confirm_new_password",
    "credential",
    "access",
    "refresh",
    "token",
}


def normalize_field_names(payload_keys: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    normalized = []
    for key in payload_keys:
        key_text = str(key).strip()
        if not key_text:
            continue
        lowered = key_text.lower()
        if lowered in SENSITIVE_FIELD_NAMES:
            continue
        normalized.append(key_text)
    return sorted(set(normalized))


def make_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)

    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, nested_value in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_FIELD_NAMES:
                normalized[key_text] = "[redacted]"
                continue
            normalized[key_text] = make_json_safe(nested_value)
        return normalized

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def resolve_resource_label(instance: Any, fallback: str = "") -> str:
    if instance is None:
        return fallback

    for attr in ("display_name", "name", "username", "code", "order_number", "reference"):
        value = getattr(instance, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return fallback or str(instance)


def create_audit_event(
    *,
    tenant,
    event_type: str,
    resource_type: str,
    summary: str,
    actor=None,
    store=None,
    resource_id: int | None = None,
    resource_label: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    actor_name = ""
    actor_role = ""
    if actor is not None:
        actor_name = getattr(actor, "display_name", "") or getattr(actor, "username", "") or ""
        actor_role = getattr(actor, "role", "") or ("superuser" if getattr(actor, "is_superuser", False) else "")

    return AuditEvent.objects.create(
        tenant=tenant,
        actor=actor if getattr(actor, "pk", None) else None,
        actor_name=actor_name,
        actor_role=actor_role,
        store=store,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_label=resource_label,
        summary=summary,
        metadata=make_json_safe(metadata or {}),
    )
