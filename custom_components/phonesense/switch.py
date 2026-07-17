from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_controls, camera_device_info, camera_setting_state, control_supported


class PhoneSenseSwitch(PhoneSenseEntity, SwitchEntity):
    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, key: str, name: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name = name

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.device.health.get("requested_modules", {}).get(self.key, False))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("requested_modules", {})[self.key] = True
        await self.coordinator.async_queue_command("apply_configuration", {"modules": {self.key: {"enabled": True}}})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("requested_modules", {})[self.key] = False
        await self.coordinator.async_queue_command("apply_configuration", {"modules": {self.key: {"enabled": False}}})


class PhoneSenseVibrationSwitch(PhoneSenseEntity, SwitchEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "actuator.vibration")
        self._attr_name = "Continuous vibration"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.device.health.get("actuators", {}).get("vibration", False))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("actuators", {})["vibration"] = True
        await self.coordinator.async_queue_command("set_vibration", {"enabled": True, "amplitude": 255})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("actuators", {})["vibration"] = False
        await self.coordinator.async_queue_command("set_vibration", {"enabled": False})


class PhoneSenseCameraSwitch(PhoneSenseEntity, SwitchEntity):
    """Expose each physical camera as an explicit stream control.

    The phone is the concurrency authority. Supported Android devices may keep
    several switches on; constrained devices report the camera they retained
    after atomically switching to the most recently enabled lens.
    """

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict) -> None:
        PhoneSenseEntity.__init__(self, coordinator, camera_id)
        self._attr_unique_id = f"{coordinator.device.device_id}_camera_control_{camera_id.replace('.', '_')}"
        self._attr_name = "Stream video"
        self._attr_device_info = camera_device_info(coordinator, camera_id, metadata)

    @property
    def is_on(self) -> bool:
        return self.key in self.coordinator.device.health.get("media_sessions", {})

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_queue_command(
            "start_camera_session",
            {"camera_id": self.key},
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_queue_command("stop_camera_session", {"camera_id": self.key})


class PhoneSenseCameraSettingSwitch(PhoneSenseEntity, SwitchEntity):
    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, key: str, name: str, default: bool = False) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"camera_{camera_id.replace('.', '_')}_setting_{key}")
        self.camera_id = camera_id
        self.setting_key = key
        self._attr_name = name
        capability = coordinator.device.capabilities.get(camera_id)
        self._attr_device_info = camera_device_info(coordinator, camera_id, capability.metadata if capability else {})
        self.default = default

    @property
    def is_on(self) -> bool:
        return bool(camera_setting_state(self.coordinator, self.camera_id, self.setting_key, self.default))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})[self.setting_key] = True
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, self.setting_key: True})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})[self.setting_key] = False
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, self.setting_key: False})


class PhoneSenseLocalRecordingSwitch(PhoneSenseEntity, SwitchEntity):
    _require_runtime_support = False
    _attr_name = "Record video on phone"

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"camera_{camera_id.replace('.', '_')}_local_recording")
        self.camera_id = camera_id
        self._attr_device_info = camera_device_info(coordinator, camera_id, metadata)

    @property
    def is_on(self) -> bool:
        return bool(camera_setting_state(self.coordinator, self.camera_id, "local_recording", False))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})["local_recording"] = True
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, "local_recording": True})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})["local_recording"] = False
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, "local_recording": False})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    modules = (
        ("location", "Location tracking"),
        ("motion", "Motion sensors"),
        ("network", "Network diagnostics"),
        ("ble_proxy", "Bluetooth proxy"),
        ("camera", "Allow camera features"),
        ("audio", "Microphone monitoring"),
    )
    entities = [PhoneSenseSwitch(coordinator, key, name) for key, name in modules if control_supported(coordinator.device, key)]
    entities.extend(
        PhoneSenseCameraSwitch(coordinator, key, capability.metadata)
        for key, capability in coordinator.device.capabilities.items()
        if key.startswith("camera.") and capability.status != "unsupported"
    )
    if control_supported(coordinator.device, "camera"):
        for camera_id, capability in coordinator.device.capabilities.items():
            if not camera_id.startswith("camera.") or capability.status == "unsupported":
                continue
            controls = camera_controls(capability.metadata)
            for key, suffix, support_key in (
                ("autofocus_hold", "Manual focus", "autofocus_hold"),
                ("torch", "Video light", "torch"),
                ("night_mode", "Night mode", "night_mode"),
                ("manual_sensor", "Manual exposure", "manual_sensor"),
            ):
                if controls.get(support_key) is True:
                    entities.append(PhoneSenseCameraSettingSwitch(coordinator, camera_id, key, suffix))
            if capability.metadata.get("local_recording") is True:
                entities.append(PhoneSenseLocalRecordingSwitch(coordinator, camera_id, capability.metadata))
    if control_supported(coordinator.device, "actuator.vibration"):
        entities.append(PhoneSenseVibrationSwitch(coordinator))
    async_add_entities(entities)
