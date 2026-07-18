from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_controls, camera_device_info, camera_setting_state, control_supported

PROFILE_OPTIONS = {
    "stationary_sensor": "Stationary sensor",
    "camera_monitor": "Camera monitor",
    "mobile_tracker": "Mobile tracker",
    "bluetooth_proxy": "Bluetooth proxy",
    "low_power": "Low power",
    "custom": "Custom",
}


def profile_option(value: object) -> str:
    """Translate the protocol profile identifier to an exact HA select option."""
    return PROFILE_OPTIONS.get(str(value), "Custom")


def device_profile_option(coordinator: PhoneSenseCoordinator) -> str:
    """Return the current profile for devices including older stored records."""
    health = getattr(coordinator.device, "health", {})
    value = health.get("profile", "stationary_sensor") if isinstance(health, dict) else "stationary_sensor"
    return profile_option(value)


class PhoneSenseProfile(PhoneSenseEntity, SelectEntity):
    _require_runtime_support = False

    _attr_name = "Usage preset"
    _attr_options = list(PROFILE_OPTIONS.values())

    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        # SelectEntity.current_option is cached, so seed it before Entity init can
        # read the state during registration.
        self._attr_current_option = device_profile_option(coordinator)
        PhoneSenseEntity.__init__(self, coordinator, "profile")
        self._attr_name = "Usage preset"

    @property
    def current_option(self) -> str:
        """Return the current option without SelectEntity's one-time cache."""
        return self._attr_current_option

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_current_option = device_profile_option(self.coordinator)
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        value = next((value for value, label in PROFILE_OPTIONS.items() if label == option), "custom")
        self.coordinator.device.health["profile"] = value
        self._attr_current_option = profile_option(value)
        self.async_write_ha_state()
        await self.coordinator.async_queue_command("apply_configuration", {"profile": value})


class PhoneSenseCameraSettingSelect(PhoneSenseEntity, SelectEntity):
    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, key: str, name: str, options: list[str], default: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"camera_{camera_id.replace('.', '_')}_setting_{key}")
        self.camera_id = camera_id
        self.setting_key = key
        self._attr_name = name
        self._attr_options = options
        capability = coordinator.device.capabilities.get(camera_id)
        self._attr_device_info = camera_device_info(coordinator, camera_id, capability.metadata if capability else {})
        self.default = default

    @property
    def current_option(self):
        value = camera_setting_state(self.coordinator, self.camera_id, self.setting_key, self.default)
        return value if value in self._attr_options else self.default

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})[self.setting_key] = option
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, self.setting_key: option})


class PhoneSenseRecordingSegmentSelect(PhoneSenseEntity, SelectEntity):
    _require_runtime_support = False
    _attr_name = "Recording clip length"
    _attr_options = ["1 minute", "5 minutes", "10 minutes"]

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict) -> None:
        PhoneSenseEntity.__init__(self, coordinator, f"camera_{camera_id.replace('.', '_')}_recording_segment_length")
        self.camera_id = camera_id
        self._attr_device_info = camera_device_info(coordinator, camera_id, metadata)

    @property
    def current_option(self):
        minutes = int(camera_setting_state(self.coordinator, self.camera_id, "recording_segment_minutes", 5))
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            return
        minutes = int(option.split()[0])
        self.coordinator.device.health.setdefault("camera_settings_by_camera", {}).setdefault(self.camera_id, {})["recording_segment_minutes"] = minutes
        await self.coordinator.async_queue_command("set_camera_settings", {"camera_id": self.camera_id, "recording_segment_minutes": minutes})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = [PhoneSenseProfile(coordinator)]
    if control_supported(coordinator.device, "camera"):
        for camera_id, capability in coordinator.device.capabilities.items():
            if not camera_id.startswith("camera.") or capability.status == "unsupported":
                continue
            controls = camera_controls(capability.metadata)
            definitions = [
                ("resolution", "Video resolution", "video_resolutions", None),
                ("photo_resolution", "Snapshot resolution", "photo_resolutions", None),
                ("white_balance", "White balance", "white_balance_options", "white_balance"),
                ("color_effect", "Color effect", "color_effect_options", "color_effect"),
                ("antibanding", "Power-line flicker reduction", "antibanding_options", "antibanding"),
            ]
            for key, suffix, metadata_key, support_key in definitions:
                options = capability.metadata.get(metadata_key, [])
                if not isinstance(options, list) or len(options) < 2 or (support_key and controls.get(support_key) is not True):
                    continue
                default = "1280x720" if "1280x720" in options else options[0]
                if key == "white_balance" and "Auto" in options:
                    default = "Auto"
                elif key == "color_effect" and "None" in options:
                    default = "None"
                elif key == "antibanding" and "Auto" in options:
                    default = "Auto"
                entities.append(PhoneSenseCameraSettingSelect(coordinator, camera_id, key, suffix, options, default))
            if capability.metadata.get("local_recording") is True:
                entities.append(PhoneSenseRecordingSegmentSelect(coordinator, camera_id, capability.metadata))
    async_add_entities(entities)
