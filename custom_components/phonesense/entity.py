from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from datetime import datetime, timezone

from .const import DOMAIN
from .coordinator import PhoneSenseCoordinator
from .models import stale_after_seconds


STREAM_MODULES = {
    "location.gps": "location",
    "motion.acceleration_rms": "motion",
    "motion.rotation_rate": "motion",
    "proximity.state": "motion",
    "environment.light_lux": "motion",
    "environment.ambient_temperature_c": "motion",
    "audio.sound_level": "audio",
    "audio.active": "audio",
    "camera.active": "camera",
    "network.queue_depth": "network",
    "network.queue_oldest_age": "network",
    "network.last_sync": "network",
    "network.transport": "network",
    "network.validated": "network",
    "network.metered": "network",
    "bluetooth.advertisements_seen": "ble_proxy",
    "bluetooth.advertisements_forwarded": "ble_proxy",
    "bluetooth.advertisements_deduplicated": "ble_proxy",
    "bluetooth.last_advertisement": "ble_proxy",
    "bluetooth.adapter": "ble_proxy",
    "bluetooth.permission": "ble_proxy",
}

ENTITY_CAPABILITIES = {
    "location.gps": "location.gps",
    "motion.acceleration_rms": "sensor.accelerometer",
    "motion.rotation_rate": "sensor.gyroscope",
    "proximity.state": "sensor.proximity",
    "environment.light_lux": "sensor.light",
    "environment.ambient_temperature_c": "sensor.ambient_temperature",
    "battery.temperature_c": "sensor.battery_temperature",
    "system.thermal_state": "system.thermal_state",
    "battery.level": "system.battery",
    "power.charging": "system.battery",
    "audio.sound_level": "audio.microphone",
    "audio.active": "audio.microphone",
    "camera.active": "camera.rear.0",
    "network.queue_depth": "system.network",
    "network.queue_oldest_age": "system.network",
    "network.last_sync": "system.network",
    "network.transport": "system.network",
    "network.validated": "system.network",
    "network.metered": "system.network",
    "bluetooth.advertisements_seen": "bluetooth.passive_scanner",
    "bluetooth.advertisements_forwarded": "bluetooth.passive_scanner",
    "bluetooth.advertisements_deduplicated": "bluetooth.passive_scanner",
    "bluetooth.last_advertisement": "bluetooth.passive_scanner",
    "bluetooth.adapter": "bluetooth.passive_scanner",
    "bluetooth.permission": "bluetooth.passive_scanner",
}

CONTROL_CAPABILITIES = {
    "location": ("location.gps",),
    "motion": ("sensor.accelerometer", "sensor.gyroscope"),
    "network": ("system.network",),
    "ble_proxy": ("bluetooth.passive_scanner",),
    "audio": ("audio.microphone",),
    "actuator.vibration": ("actuator.vibration",),
    "actuator.flashlight": ("actuator.flashlight",),
    "display.screen": ("display.screen",),
    "media.playback": ("media.playback",),
}

_CONTROLLABLE_CAPABILITY_STATUSES = {
    "available",
    "permission_required",
    "temporarily_unavailable",
    "failed",
}


def control_supported(device, key: str) -> bool:
    """Return whether hardware/OS support a persistent control.

    Permission-required and failed capabilities remain represented so a user
    can repair permission state without entity-ID churn. Truly unsupported or
    OS-restricted controls are omitted instead of becoming dead entities.
    """
    if key == "camera":
        capabilities = [value for name, value in device.capabilities.items() if name.startswith("camera.")]
    else:
        capabilities = [device.capabilities[name] for name in CONTROL_CAPABILITIES.get(key, ()) if name in device.capabilities]
    return any(capability.status in _CONTROLLABLE_CAPABILITY_STATUSES for capability in capabilities)


def camera_display_name(camera_id: str, metadata: dict | None = None) -> str:
    """Return a stable human label that still distinguishes multiple same-facing lenses."""
    metadata = metadata or {}
    parts = camera_id.split(".")
    facing = str(metadata.get("facing") or (parts[1] if len(parts) > 1 else "camera")).replace("_", " ").title()
    index = int(parts[-1]) if parts and parts[-1].isdigit() else 0
    return f"{facing} camera" if index == 0 else f"{facing} camera {index + 1}"


def camera_device_info(coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict | None = None) -> dict:
    """Place every lens and its settings on a readable child device page."""
    label = camera_display_name(camera_id, metadata)
    hardware_id = str((metadata or {}).get("hardware_id", "")).strip()
    model = f"{coordinator.device.platform} {label.lower()}"
    if hardware_id:
        model = f"{model} (hardware {hardware_id})"
    return {
        "identifiers": {(DOMAIN, f"{coordinator.device.device_id}:{camera_id}")},
        "name": f"{coordinator.device.name} {label}",
        "manufacturer": "PhoneSense",
        "model": model,
        "sw_version": coordinator.device.app_version,
        "via_device": (DOMAIN, coordinator.device.device_id),
    }


def camera_setting_state(coordinator: PhoneSenseCoordinator, camera_id: str, key: str, default):
    """Read a per-camera setting with a legacy-global fallback during migration."""
    per_camera = coordinator.device.health.get("camera_settings_by_camera", {})
    if isinstance(per_camera, dict):
        settings = per_camera.get(camera_id, {})
        if isinstance(settings, dict) and key in settings:
            return settings[key]
    return coordinator.device.health.get("camera_settings", {}).get(key, default)


def camera_controls(metadata: dict | None) -> dict:
    controls = (metadata or {}).get("controls", {})
    return controls if isinstance(controls, dict) else {}


def module_for_entity_key(key: str) -> str | None:
    """Return the configuration module that controls an entity key."""
    if key.startswith("camera."):
        return "camera"
    return STREAM_MODULES.get(key)


def module_enabled(coordinator: PhoneSenseCoordinator, module: str) -> bool:
    """Use the phone-reported effective configuration as the source of truth."""
    runtime_modules = coordinator.device.health.get("modules", {})
    if isinstance(runtime_modules, dict):
        runtime_state = runtime_modules.get(module)
        if runtime_state in {"active", "enabled"}:
            return True
        if runtime_state == "disabled":
            return False
    configuration = coordinator.device.health.get("effective_configuration", {})
    modules = configuration.get("modules", {}) if isinstance(configuration, dict) else {}
    value = modules.get(module) if isinstance(modules, dict) else None
    return isinstance(value, dict) and value.get("enabled") is True


def entity_supported(
    coordinator: PhoneSenseCoordinator,
    key: str,
    capability: str | None = None,
) -> bool:
    """Check whether the phone reports runtime support for an entity."""
    capability = capability or ENTITY_CAPABILITIES.get(key)
    return key in coordinator.device.streams or (
        capability is not None and coordinator.device.capability_available(capability)
    )


def entity_supported_and_enabled(
    coordinator: PhoneSenseCoordinator,
    key: str,
    capability: str | None = None,
) -> bool:
    """Check runtime support and the effective module switch."""
    supported = entity_supported(coordinator, key, capability)
    controlling_module = module_for_entity_key(key)
    return supported and (
        controlling_module is None or module_enabled(coordinator, controlling_module)
    )


class PhoneSenseEntity(CoordinatorEntity[PhoneSenseCoordinator]):
    _attr_has_entity_name = True
    _require_runtime_support = True

    def __init__(self, coordinator: PhoneSenseCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{coordinator.device.device_id}_{key.replace('.', '_')}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device.device_id)},
            "name": coordinator.device.name,
            "manufacturer": "PhoneSense",
            "model": f"{coordinator.device.platform} sensor node",
            "sw_version": coordinator.device.app_version,
        }

    @property
    def available(self) -> bool:
        supported = (
            not self._require_runtime_support
            or self.key in self.coordinator.device.streams
            or self.coordinator.device.capability_available(ENTITY_CAPABILITIES.get(self.key, self.key))
        )
        controlling_module = module_for_entity_key(self.key)
        stale_after = stale_after_seconds(self.coordinator.device)
        fresh = self.coordinator.device.last_seen is not None and (datetime.now(timezone.utc) - self.coordinator.device.last_seen).total_seconds() <= stale_after
        return super().available and supported and fresh and (
            controlling_module is None or module_enabled(self.coordinator, controlling_module)
        )

    @property
    def native_value(self):
        state = self.coordinator.device.streams.get(self.key)
        return state.value if state else None

    @property
    def extra_state_attributes(self):
        state = self.coordinator.device.streams.get(self.key)
        if not state:
            return None
        return {"observed_at": state.observed_at, "quality": state.quality, "sequence": state.last_sequence}
