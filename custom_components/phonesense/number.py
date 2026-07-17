from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_controls, camera_device_info, camera_setting_state, control_supported


class PhoneSenseInterval(PhoneSenseEntity, NumberEntity):
    _require_runtime_support = False

    _attr_native_min_value = 1
    _attr_native_max_value = 3600
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: PhoneSenseCoordinator, key: str, name: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self):
        return self.coordinator.device.health.get("intervals", {}).get(self.key, 5)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.device.health.setdefault("intervals", {})[self.key] = value
        if self.key == "location_interval":
            payload = {"modules": {"location": {"interval_ms": int(value * 1000)}}}
        else:
            payload = {"modules": {"motion": {"publish_interval_ms": int(value * 1000)}}}
        await self.coordinator.async_queue_command("apply_configuration", payload)


class PhoneSenseCameraSettingNumber(PhoneSenseEntity, NumberEntity):
    _require_runtime_support = False
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, key: str, name: str, minimum: int, maximum: int, default: int) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"camera_{camera_id.replace('.', '_')}_setting_{key}")
        self.camera_id = camera_id
        self.setting_key = key
        self._attr_name = name
        capability = coordinator.device.capabilities.get(camera_id)
        self._attr_device_info = camera_device_info(coordinator, camera_id, capability.metadata if capability else {})
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = 1
        self.default = default

    @property
    def native_value(self):
        return camera_setting_state(self.coordinator, self.camera_id, self.setting_key, self.default)

    async def async_set_native_value(self, value: float) -> None:
        bounded = int(max(self._attr_native_min_value, min(self._attr_native_max_value, value)))
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})[self.setting_key] = bounded
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, self.setting_key: bounded})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = []
    if control_supported(coordinator.device, "location"):
        entities.append(PhoneSenseInterval(coordinator, "location_interval", "Location interval"))
    if control_supported(coordinator.device, "motion"):
        entities.append(PhoneSenseInterval(coordinator, "motion_publish_interval", "Motion publish interval"))
    if control_supported(coordinator.device, "camera"):
        for camera_id, capability in coordinator.device.capabilities.items():
            if not camera_id.startswith("camera.") or capability.status == "unsupported":
                continue
            controls = camera_controls(capability.metadata)
            definitions = [
                ("quality", "JPEG stream quality", 0, 100, 46, "quality", "%"),
                ("frame_rate", "Frame rate", int(capability.metadata.get("frame_rate_min", 5)), int(capability.metadata.get("frame_rate_max", 30)), 15, "frame_rate", "fps"),
                ("focus_distance_percent", "Focus distance", 0, 100, 0, "focus_distance", "%"),
                ("exposure_compensation_percent", "Automatic exposure brightness", 0, 100, 50, "exposure_compensation", "%"),
                ("iso_percent", "ISO level", 0, 100, 10, "iso", "%"),
                ("manual_exposure_percent", "Exposure time", 0, 100, 10, "manual_exposure", "%"),
            ]
            for key, suffix, minimum, maximum, default, support_key, unit in definitions:
                if controls.get(support_key) is True and maximum >= minimum:
                    entity = PhoneSenseCameraSettingNumber(coordinator, camera_id, key, suffix, minimum, maximum, default)
                    entity._attr_native_unit_of_measurement = unit
                    entities.append(entity)
    async_add_entities(entities)
