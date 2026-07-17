from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_device_info, entity_supported

STREAMS = {
    "battery.level": ("Battery level", SensorDeviceClass.BATTERY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "environment.ambient_temperature_c": ("Ambient temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "battery.temperature_c": ("Battery temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "system.thermal_state": ("Thermal status", None, None, None),
    "motion.acceleration_rms": ("Motion", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.acceleration_x": ("Acceleration X", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.acceleration_y": ("Acceleration Y", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.acceleration_z": ("Acceleration Z", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.rotation_rate": ("Rotation rate", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.rotation_x": ("Rotation X", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.rotation_y": ("Rotation Y", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.rotation_z": ("Rotation Z", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.magnetic_field_x": ("Magnetic field X", None, "µT", SensorStateClass.MEASUREMENT),
    "motion.magnetic_field_y": ("Magnetic field Y", None, "µT", SensorStateClass.MEASUREMENT),
    "motion.magnetic_field_z": ("Magnetic field Z", None, "µT", SensorStateClass.MEASUREMENT),
    "motion.magnetic_field_strength": ("Magnetic field strength", None, "µT", SensorStateClass.MEASUREMENT),
    "motion.pitch": ("Pitch", None, "°", SensorStateClass.MEASUREMENT),
    "motion.roll": ("Roll", None, "°", SensorStateClass.MEASUREMENT),
    "motion.yaw": ("Yaw", None, "°", SensorStateClass.MEASUREMENT),
    "motion.gravity_x": ("Gravity X", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.gravity_y": ("Gravity Y", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.gravity_z": ("Gravity Z", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.user_acceleration_x": ("User acceleration X", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.user_acceleration_y": ("User acceleration Y", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.user_acceleration_z": ("User acceleration Z", None, "m/s²", SensorStateClass.MEASUREMENT),
    "motion.calibrated_rotation_x": ("Calibrated rotation X", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.calibrated_rotation_y": ("Calibrated rotation Y", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.calibrated_rotation_z": ("Calibrated rotation Z", None, "rad/s", SensorStateClass.MEASUREMENT),
    "motion.magnetic_accuracy": ("Magnetic calibration", None, None, None),
    "environment.pressure": ("Atmospheric pressure", SensorDeviceClass.ATMOSPHERIC_PRESSURE, "kPa", SensorStateClass.MEASUREMENT),
    "environment.relative_altitude": ("Relative altitude", SensorDeviceClass.DISTANCE, "m", SensorStateClass.MEASUREMENT),
    "activity.steps": ("Steps", None, "steps", SensorStateClass.TOTAL_INCREASING),
    "activity.distance": ("Walking and running distance", SensorDeviceClass.DISTANCE, "m", SensorStateClass.TOTAL_INCREASING),
    "activity.floors_ascended": ("Floors ascended", None, "floors", SensorStateClass.TOTAL_INCREASING),
    "activity.floors_descended": ("Floors descended", None, "floors", SensorStateClass.TOTAL_INCREASING),
    "activity.pace": ("Current pace", None, "s/m", SensorStateClass.MEASUREMENT),
    "activity.cadence": ("Current cadence", None, "steps/min", SensorStateClass.MEASUREMENT),
    "activity.type": ("Motion activity", None, None, None),
    "activity.confidence": ("Motion confidence", None, None, None),
    "device.orientation": ("Orientation", None, None, None),
    "location.heading_magnetic": ("Magnetic heading", None, "°", SensorStateClass.MEASUREMENT),
    "location.heading_true": ("True heading", None, "°", SensorStateClass.MEASUREMENT),
    "location.heading_accuracy": ("Heading accuracy", None, "°", SensorStateClass.MEASUREMENT),
    "environment.light_lux": ("Light level", SensorDeviceClass.ILLUMINANCE, "lx", SensorStateClass.MEASUREMENT),
    "audio.sound_level": ("Sound level", None, "dBFS", SensorStateClass.MEASUREMENT),
    "audio.peak_level": ("Peak sound level", None, "dBFS", SensorStateClass.MEASUREMENT),
    "audio.rolling_average": ("Average sound level", None, "dBFS", SensorStateClass.MEASUREMENT),
    "display.brightness": ("Screen brightness", None, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "storage.available": ("Available storage", SensorDeviceClass.DATA_SIZE, "B", SensorStateClass.MEASUREMENT),
    "storage.total": ("Total storage", SensorDeviceClass.DATA_SIZE, "B", SensorStateClass.MEASUREMENT),
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
    "motion.acceleration_x": "sensor.accelerometer",
    "motion.acceleration_y": "sensor.accelerometer",
    "motion.acceleration_z": "sensor.accelerometer",
    "motion.rotation_rate": "sensor.gyroscope",
    "motion.rotation_x": "sensor.gyroscope",
    "motion.rotation_y": "sensor.gyroscope",
    "motion.rotation_z": "sensor.gyroscope",
    "motion.magnetic_field_x": "sensor.magnetometer",
    "motion.magnetic_field_y": "sensor.magnetometer",
    "motion.magnetic_field_z": "sensor.magnetometer",
    "motion.magnetic_field_strength": "sensor.magnetometer",
    "motion.pitch": "sensor.device_motion",
    "motion.roll": "sensor.device_motion",
    "motion.yaw": "sensor.device_motion",
    "motion.gravity_x": "sensor.device_motion",
    "motion.gravity_y": "sensor.device_motion",
    "motion.gravity_z": "sensor.device_motion",
    "motion.user_acceleration_x": "sensor.device_motion",
    "motion.user_acceleration_y": "sensor.device_motion",
    "motion.user_acceleration_z": "sensor.device_motion",
    "motion.calibrated_rotation_x": "sensor.device_motion",
    "motion.calibrated_rotation_y": "sensor.device_motion",
    "motion.calibrated_rotation_z": "sensor.device_motion",
    "motion.magnetic_accuracy": "sensor.device_motion",
    "environment.pressure": "sensor.barometer",
    "environment.relative_altitude": "sensor.barometer",
    "activity.steps": "sensor.pedometer",
    "activity.distance": "sensor.pedometer",
    "activity.floors_ascended": "sensor.pedometer",
    "activity.floors_descended": "sensor.pedometer",
    "activity.pace": "sensor.pedometer",
    "activity.cadence": "sensor.pedometer",
    "activity.type": "sensor.motion_activity",
    "activity.confidence": "sensor.motion_activity",
    "device.orientation": "sensor.orientation",
    "location.heading_magnetic": "location.heading",
    "location.heading_true": "location.heading",
    "location.heading_accuracy": "location.heading",
    "environment.light_lux": "sensor.light",
    "audio.sound_level": "audio.microphone",
    "audio.peak_level": "audio.microphone",
    "audio.rolling_average": "audio.microphone",
    "display.brightness": "system.screen_brightness",
    "storage.available": "system.storage",
    "storage.total": "system.storage",
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


class PhoneSenseCameraAnalysisSensor(PhoneSenseEntity, SensorEntity):
    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, suffix: str, name: str, unit: str | None) -> None:
        key = f"{camera_id}.{suffix}"
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        capability = coordinator.device.capabilities.get(camera_id)
        self._attr_device_info = camera_device_info(coordinator, camera_id, capability.metadata if capability else {})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = [
        PhoneSenseSensor(coordinator, key)
        for key in STREAMS
        if entity_supported(coordinator, key, CAPABILITIES[key])
    ]
    if any(key.startswith("camera.") and value.status == "available" for key, value in coordinator.device.capabilities.items()):
        entities.append(PhoneSenseRecordingSensor(coordinator))
    for camera_id, capability in coordinator.device.capabilities.items():
        if not camera_id.startswith("camera.") or capability.status != "available" or capability.metadata.get("analytics") is not True:
            continue
        entities.extend([
            PhoneSenseCameraAnalysisSensor(coordinator, camera_id, "scene_brightness", "Scene brightness", PERCENTAGE),
            PhoneSenseCameraAnalysisSensor(coordinator, camera_id, "motion_score", "Visual motion score", PERCENTAGE),
            PhoneSenseCameraAnalysisSensor(coordinator, camera_id, "person_count", "People detected", "people"),
        ])
    async_add_entities(entities)
