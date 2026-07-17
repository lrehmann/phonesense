from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_device_info


def available_cameras(coordinator: PhoneSenseCoordinator) -> list[tuple[str, str]]:
    """Return runtime-supported cameras independently of current module state."""
    return [
        (key, value.metadata.get("facing", key))
        for key, value in coordinator.device.capabilities.items()
        if key.startswith("camera.") and value.status == "available"
    ]


class PhoneSenseCamera(PhoneSenseEntity, Camera):
    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict) -> None:
        PhoneSenseEntity.__init__(self, coordinator, camera_id)
        Camera.__init__(self)
        self._attr_name = "Live view"
        self._attr_device_info = camera_device_info(coordinator, camera_id, metadata)
        # The phone already uploads a bounded JPEG relay. Home Assistant's
        # native MJPEG still-stream calls async_camera_image at this interval
        # and avoids an unnecessary, higher-latency FFmpeg/HLS transcode.
        self._attr_supported_features = CameraEntityFeature.ON_OFF
        self._attr_frame_interval = 0.2

    @property
    def is_streaming(self) -> bool:
        return self.coordinator.get_live_frame(self.key) is not None

    @property
    def is_on(self) -> bool:
        session = self.coordinator.device.health.get("media_sessions", {}).get(self.key, {})
        return bool(session)

    @property
    def supported_features(self) -> CameraEntityFeature:
        return CameraEntityFeature.ON_OFF

    async def async_camera_image(self, width=None, height=None):
        if live := self.coordinator.get_live_frame(self.key):
            return live
        snapshot = self.coordinator.device.health.get("snapshots", {}).get(self.key)
        if not snapshot:
            return None
        try:
            with open(snapshot["path"], "rb") as image:
                return image.read()
        except OSError:
            return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_queue_command(
            "start_camera_session",
            {"camera_id": self.key},
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_queue_command("stop_camera_session", {"camera_id": self.key})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    cameras = available_cameras(coordinator)
    async_add_entities([
        PhoneSenseCamera(coordinator, key, coordinator.device.capabilities[key].metadata)
        for key, _facing in cameras
    ])
