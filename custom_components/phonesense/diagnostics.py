from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry


_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "token", "secret", "authorization", "url", "path",
    "endpoint", "endpoint_url", "endpoint_urls", "local_addresses", "ip_addresses",
    "data_base64", "latitude", "longitude", "address", "manufacturer_data", "service_data",
}

_SENSITIVE_TEXT = (
    (re.compile(r"(?i)\bbearer\s+[^\s\"']+"), "Bearer <redacted>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "<redacted-token>"),
    (re.compile(r"(?i)\b(?:https?|wss?|rtsp)://[^\s\"'<>]+"), "<redacted-url>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<redacted-ip>"),
    (re.compile(r"(?<![\d.])-?\d{1,2}(?:\.\d{3,})\s*[,/]\s*-?\d{1,3}(?:\.\d{3,})(?![\d.])"), "<redacted-location>"),
)


def _redact(value, key: str = ""):
    """Keep diagnostic shape while removing credentials and direct private data."""
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS or any(part in lowered for part in ("token", "secret", "password", "endpoint", "url", "address", "latitude", "longitude", "ip_address")):
        return "<redacted>"
    if isinstance(value, dict):
        return {name: _redact(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str):
        for pattern, replacement in _SENSITIVE_TEXT:
            value = pattern.sub(replacement, value)
    return value


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    device = coordinator.device
    return {
        "device_id": device.device_id,
        "name": device.name,
        "platform": device.platform,
        "os_version": device.os_version,
        "app_version": device.app_version,
        "capabilities": _redact({key: {"status": value.status, "metadata": value.metadata} for key, value in device.capabilities.items()}),
        "health": _redact(device.health),
        "stream_ids": sorted(device.streams),
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
    }
