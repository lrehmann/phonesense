from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import datetime, timezone

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_device_info, entity_supported
from .models import stale_after_seconds


STREAMS = {
    "proximity.state": ("Proximity", BinarySensorDeviceClass.OCCUPANCY),
    "power.charging": ("Charging", BinarySensorDeviceClass.BATTERY_CHARGING),
    "camera.active": ("Camera active", BinarySensorDeviceClass.RUNNING),
    "audio.active": ("Microphone active", BinarySensorDeviceClass.RUNNING),
    "system.low_power_mode": ("Low Power Mode", BinarySensorDeviceClass.POWER),
}
CAPABILITIES = {
    "proximity.state": "sensor.proximity",
    "power.charging": "system.battery",
    "camera.active": "camera.rear.0",
    "audio.active": "audio.microphone",
    "system.low_power_mode": "system.low_power_mode",
}


class PhoneSenseBinarySensor(PhoneSenseEntity, BinarySensorEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator, key: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name, self._attr_device_class = STREAMS[key]

    @property
    def is_on(self):
        value = self.native_value
        return value is True or value in ("on", "active", "charging", "near")


class PhoneSenseOnlineBinarySensor(PhoneSenseEntity, BinarySensorEntity):
    """Always-present device heartbeat entity; false means the node is stale."""

    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "online")
        self._attr_name = "Online"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        last_seen = self.coordinator.device.last_seen
        if last_seen is None:
            return False
        stale_after = stale_after_seconds(self.coordinator.device)
        return (datetime.now(timezone.utc) - last_seen).total_seconds() <= stale_after


class PhoneSenseCameraOccupancySensor(PhoneSenseEntity, BinarySensorEntity):
    _require_runtime_support = False
    _attr_name = "Person occupancy"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"{camera_id}.occupancy")
        capability = coordinator.device.capabilities.get(camera_id)
        self._attr_device_info = camera_device_info(coordinator, camera_id, capability.metadata if capability else {})

    @property
    def is_on(self):
        return self.native_value is True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = [
        PhoneSenseOnlineBinarySensor(coordinator),
        *[
            PhoneSenseBinarySensor(coordinator, key)
            for key in STREAMS
            if entity_supported(coordinator, key, CAPABILITIES[key])
        ],
    ]
    entities.extend(
        PhoneSenseCameraOccupancySensor(coordinator, camera_id)
        for camera_id, capability in coordinator.device.capabilities.items()
        if camera_id.startswith("camera.")
        and capability.status == "available"
        and capability.metadata.get("analytics") is True
    )
    async_add_entities(entities)
