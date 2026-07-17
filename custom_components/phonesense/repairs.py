"""Home Assistant repair issues for PhoneSense runtime failures."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue, async_delete_issue

from .const import DOMAIN
from .models import stale_after_seconds


def _issue_id(prefix: str, device_id: str) -> str:
    return f"{prefix}_{re.sub(r'[^a-zA-Z0-9_]', '_', device_id)}"


def update_device_issues(hass: HomeAssistant, device: Any) -> None:
    """Create or clear actionable issues based on the latest phone health."""
    stale_after = stale_after_seconds(device)
    stale = device.last_seen is None or (datetime.now(timezone.utc) - device.last_seen).total_seconds() > stale_after
    stale_id = _issue_id("stale_device", device.device_id)
    if stale:
        async_create_issue(
            hass, DOMAIN, stale_id, is_fixable=False, is_persistent=True,
            severity=IssueSeverity.WARNING, translation_key="stale_device",
            translation_placeholders={"device_name": device.name},
        )
    else:
        async_delete_issue(hass, DOMAIN, stale_id)

    permission_id = _issue_id("permissions", device.device_id)
    blocked = [cap.id for cap in device.capabilities.values() if cap.status in {"permission_required", "failed"}]
    if blocked:
        async_create_issue(
            hass, DOMAIN, permission_id, is_fixable=False, is_persistent=True,
            severity=IssueSeverity.WARNING, translation_key="permissions_required",
            translation_placeholders={"device_name": device.name, "capabilities": ", ".join(sorted(blocked))},
        )
    else:
        async_delete_issue(hass, DOMAIN, permission_id)

    protocol_id = _issue_id("incompatible_protocol", device.device_id)
    protocol_error = device.health.get("protocol_error")
    if protocol_error:
        async_create_issue(
            hass, DOMAIN, protocol_id, is_fixable=False, is_persistent=True,
            severity=IssueSeverity.ERROR, translation_key="incompatible_protocol",
            translation_placeholders={"device_name": device.name, "error": str(protocol_error)},
        )
    else:
        async_delete_issue(hass, DOMAIN, protocol_id)
