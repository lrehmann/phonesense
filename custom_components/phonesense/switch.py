from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_controls, camera_device_info, camera_setting_state, control_supported

CAPABILITY_SWITCH_NAMES = {
    "location.gps": "GPS",
    "location.heading": "Compass heading",
    "sensor.accelerometer": "Accelerometer",
    "sensor.barometer": "Barometer",
    "sensor.device_motion": "Device motion",
    "sensor.gyroscope": "Gyroscope",
    "sensor.magnetometer": "Magnetometer",
    "sensor.motion_activity": "Motion activity",
    "sensor.orientation": "Orientation",
    "sensor.pedometer": "Pedometer",
    "sensor.proximity": "Proximity",
    "system.battery": "Battery telemetry",
    "system.low_power_mode": "Low power status",
    "system.network": "Network diagnostics",
    "system.screen_brightness": "Screen brightness telemetry",
    "system.storage": "Storage telemetry",
    "system.thermal_state": "Thermal status",
}


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


class PhoneSenseCapabilitySwitch(PhoneSenseEntity, SwitchEntity):
    """Enable one runtime-discovered data source without duplicating hardware sessions."""

    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, capability_id: str, metadata: dict) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"collect_{capability_id}")
        self.capability_id = capability_id
        self.default = bool(metadata.get("default_enabled", False))
        label = capability_id.removeprefix("sensor.").removeprefix("system.").removeprefix("location.")
        self._attr_name = CAPABILITY_SWITCH_NAMES.get(
            capability_id,
            label.replace("_", " ").replace(".", " ").title(),
        )

    @property
    def is_on(self) -> bool:
        states = self.coordinator.device.health.get("requested_capabilities", {})
        return bool(states.get(self.capability_id, self.default)) if isinstance(states, dict) else self.default

    async def _set_enabled(self, enabled: bool) -> None:
        self.coordinator.device.health.setdefault("requested_capabilities", {})[self.capability_id] = enabled
        await self.coordinator.async_queue_command(
            "set_capability_enabled",
            {"capability_id": self.capability_id, "enabled": enabled},
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_enabled(False)


class PhoneSenseAudioSwitch(PhoneSenseEntity, SwitchEntity):
    """Control microphone monitoring with explicit local arming.

    Audio is privacy-sensitive and must not be started indirectly by a generic
    configuration update. The app reports the actual capture-session state,
    so the switch cannot remain on when the audio engine has stopped.
    """

    _require_runtime_support = False
    _ignore_module_gate = True

    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "audio")
        self._attr_name = "Microphone monitoring (arm on phone)"

    @property
    def is_on(self) -> bool:
        return self.coordinator.device.health.get("modules", {}).get("audio") == "active"

    @property
    def extra_state_attributes(self):
        errors = self.coordinator.device.health.get("module_errors", {})
        return {
            "configured": bool(self.coordinator.device.health.get("requested_modules", {}).get("audio", False)),
            "local_arming_required": True,
            "last_error": errors.get("audio") if isinstance(errors, dict) else None,
        }

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("requested_modules", {})["audio"] = True
        await self.coordinator.async_queue_command(
            "apply_configuration",
            {"modules": {"audio": {"enabled": True}}},
        )
        await self.coordinator.async_queue_command(
            "start_audio_session",
            requires_local_arming=True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("requested_modules", {})["audio"] = False
        await self.coordinator.async_queue_command("stop_audio_session")
        await self.coordinator.async_queue_command(
            "apply_configuration",
            {"modules": {"audio": {"enabled": False}}},
        )


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

    _ignore_module_gate = True

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
    individually_controllable = {
        capability_id
        for capability_id, capability in coordinator.device.capabilities.items()
        if capability.metadata.get("controllable") is True and capability.status != "unsupported"
    }
    has_camera_switches = any(
        capability_id.startswith("camera.") and capability.status != "unsupported"
        for capability_id, capability in coordinator.device.capabilities.items()
    )
    modules = (
        ("location", "Location tracking"),
        ("motion", "Motion sensors"),
        ("network", "Network diagnostics"),
        ("ble_proxy", "Bluetooth proxy"),
        ("camera", "Allow camera features"),
        ("audio", "Microphone monitoring"),
    )
    shadowed_modules = {
        "location": any(capability_id.startswith("location.") for capability_id in individually_controllable),
        "motion": any(capability_id.startswith("sensor.") for capability_id in individually_controllable),
        "network": "system.network" in individually_controllable,
        "camera": has_camera_switches,
        "audio": True,
    }
    entities = [
        PhoneSenseSwitch(coordinator, key, name)
        for key, name in modules
        if control_supported(coordinator.device, key) and not shadowed_modules.get(key, False)
    ]
    entities.extend(
        PhoneSenseCapabilitySwitch(coordinator, capability_id, capability.metadata)
        for capability_id, capability in coordinator.device.capabilities.items()
        if capability.metadata.get("controllable") is True
        and capability.status != "unsupported"
        and not capability_id.startswith("camera.")
        and capability_id not in {"display.screen", "audio.microphone"}
    )
    entities.extend(
        PhoneSenseCameraSwitch(coordinator, key, capability.metadata)
        for key, capability in coordinator.device.capabilities.items()
        if key.startswith("camera.") and capability.status != "unsupported"
    )
    if control_supported(coordinator.device, "audio"):
        entities.append(PhoneSenseAudioSwitch(coordinator))
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
