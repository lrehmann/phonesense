from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, entity_supported

STREAMS = {
    "battery.level": ("Battery level", SensorDeviceClass.BATTERY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "environment.ambient_temperature_c": ("Ambient temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "battery.temperature_c": ("Battery temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "system.thermal_state": ("Thermal status", None, None, None),
    "motion.acceleration_rms": ("Motion", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.rotation_rate": ("Rotation rate", None, "rad/s", SensorStateClass.MEASUREMENT),
    "environment.light_lux": ("Light level", SensorDeviceClass.ILLUMINANCE, "lx", SensorStateClass.MEASUREMENT),
    "audio.sound_level": ("Sound level", None, "dBFS", SensorStateClass.MEASUREMENT),
    "network.queue_depth": ("Queue depth", None, "samples", SensorStateClass.MEASUREMENT),
    "network.queue_oldest_age": ("Oldest queued sample", None, "s", SensorStateClass.MEASUREMENT),
    "network.last_sync": ("Last sync", None, None, None),
    "network.transport": ("Network type", None, None, None),
    "network.validated": ("Network validated", None, None, None),
    "network.metered": ("Network metered", None, None, None),
    "bluetooth.advertisements_seen": ("Bluetooth advertisements seen", None, "advertisements", None),
    "bluetooth.advertisements_forwarded": ("Bluetooth advertisements forwarded", None, "advertisements", None),
    "bluetooth.advertisements_deduplicated": ("Bluetooth advertisements deduplicated", None, "advertisements", None),
    "bluetooth.last_advertisement": ("Last Bluetooth advertisement", None, None, None),
    "bluetooth.adapter": ("Bluetooth adapter", None, None, None),
    "bluetooth.permission": ("Bluetooth permission", None, None, None),
}
CAPABILITIES = {
    "battery.level": "system.battery",
    "environment.ambient_temperature_c": "sensor.ambient_temperature",
    "battery.temperature_c": "sensor.battery_temperature",
    "system.thermal_state": "system.thermal_state",
    "motion.acceleration_rms": "sensor.accelerometer",
    "motion.rotation_rate": "sensor.gyroscope",
    "environment.light_lux": "sensor.light",
    "audio.sound_level": "audio.microphone",
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

DIAGNOSTIC_STREAMS = {
    "system.thermal_state",
    "network.queue_depth",
    "network.queue_oldest_age",
    "network.last_sync",
    "network.transport",
    "network.validated",
    "network.metered",
    "bluetooth.advertisements_seen",
    "bluetooth.advertisements_forwarded",
    "bluetooth.advertisements_deduplicated",
    "bluetooth.last_advertisement",
    "bluetooth.adapter",
    "bluetooth.permission",
}
NOISY_DIAGNOSTICS = {
    "network.queue_depth",
    "network.queue_oldest_age",
    "network.last_sync",
    "bluetooth.last_advertisement",
}

class PhoneSenseSensor(PhoneSenseEntity, SensorEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator, key: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name = STREAMS[key][0]
        self._attr_device_class = STREAMS[key][1]
        self._attr_native_unit_of_measurement = STREAMS[key][2]
        self._attr_state_class = STREAMS[key][3]
        if key in DIAGNOSTIC_STREAMS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if key in NOISY_DIAGNOSTICS:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.key == "network.queue_oldest_age":
            queue = self.coordinator.device.health.get("queue", {})
            if not isinstance(queue, dict):
                return None
            if isinstance(queue.get("oldest_age_seconds"), (int, float)):
                return queue["oldest_age_seconds"]
            if isinstance(queue.get("oldest_age_ms"), (int, float)):
                return queue["oldest_age_ms"] / 1000
            return None
        if self.key == "network.last_sync":
            return self.coordinator.device.health.get("last_sync_at")
        if self.key in {"network.validated", "network.metered"}:
            network = self.coordinator.device.health.get("network", {})
            return network.get(self.key.removeprefix("network.")) if isinstance(network, dict) else None
        if self.key.startswith("bluetooth."):
            bluetooth = self.coordinator.device.health.get("ble", {})
            if not isinstance(bluetooth, dict):
                return None
            mapping = {
                "bluetooth.advertisements_seen": "seen",
                "bluetooth.advertisements_forwarded": "forwarded",
                "bluetooth.advertisements_deduplicated": "deduplicated",
                "bluetooth.last_advertisement": "last_advertisement_at",
                "bluetooth.adapter": "adapter",
                "bluetooth.permission": "permission",
            }
            return bluetooth.get(mapping[self.key])
        return super().native_value


class PhoneSenseRecordingSensor(PhoneSenseEntity, SensorEntity):
    _require_runtime_support = False
    _attr_name = "Local camera recordings"
    _attr_native_unit_of_measurement = "recordings"
    _attr_icon = "mdi:video-box"

    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "camera_local_recordings")

    @property
    def native_value(self):
        return int(self.coordinator.device.health.get("local_recordings", {}).get("count", 0))

    @property
    def extra_state_attributes(self):
        state = self.coordinator.device.health.get("local_recordings", {})
        return {
            "recording": bool(state.get("active", False)),
            "stored_bytes": int(state.get("bytes", 0)),
            "pending_uploads": int(state.get("pending_uploads", 0)),
            "latest_recording_at": state.get("latest_at"),
            "latest_camera_id": state.get("latest_camera_id"),
            "media_source": f"media-source://phonesense/{self.coordinator.device.device_id}",
        }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = [
        PhoneSenseSensor(coordinator, key)
        for key in STREAMS
        if entity_supported(coordinator, key, CAPABILITIES[key])
    ]
    if any(key.startswith("camera.") and value.status == "available" for key, value in coordinator.device.capabilities.items()):
        entities.append(PhoneSenseRecordingSensor(coordinator))
    async_add_entities(entities)
