from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class StreamState:
    stream_id: str
    value: Any = None
    unit: str | None = None
    kind: str = "state"
    observed_at: str | None = None
    received_at: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    last_sequence: int = -1


@dataclass(slots=True)
class Capability:
    id: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Command:
    command_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    issued_at: str = ""
    expires_at: str | None = None
    requires_local_arming: bool = False
    state: str = "pending"
    result: dict[str, Any] | None = None


@dataclass(slots=True)
class PhoneSenseDevice:
    device_id: str
    name: str
    platform: str = "unknown"
    os_version: str = "unknown"
    app_version: str = "unknown"
    capabilities: dict[str, Capability] = field(default_factory=dict)
    streams: dict[str, StreamState] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    commands: dict[str, Command] = field(default_factory=dict)
    seen_keys: set[tuple[str, str, int]] = field(default_factory=set)
    seen_order: list[tuple[str, str, int]] = field(default_factory=list)
    last_seen: datetime | None = None

    def capability_available(self, capability_id: str) -> bool:
        capability = self.capabilities.get(capability_id)
        return capability is not None and capability.status == "available"


_EXECUTION_STALE_SECONDS = {
    "android_foreground_service": 300,
    "ios_foreground": 300,
    "ios_foreground_camera": 300,
    "ios_background_audio": 900,
    "ios_background_location": 3600,
    "ios_opportunistic": 21600,
}


def stale_after_seconds(device: PhoneSenseDevice) -> int:
    """Return a platform-honest heartbeat window for this device."""
    configured = device.health.get("stale_after_seconds")
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        return max(60, min(int(configured), 86400))
    mode = device.health.get("expected_execution_mode")
    if isinstance(mode, str):
        return _EXECUTION_STALE_SECONDS.get(mode, 900)
    return 900
