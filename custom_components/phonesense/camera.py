from __future__ import annotations

from base64 import b64decode

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_device_info

# Home Assistant's still-image MJPEG proxy closes the browser stream when the
# first camera image is None. Keep an active PhoneSense session connected while
# its first frame is in flight (or while the phone is recovering capture) so
# the existing live-view dialog can transition to real frames without requiring
# the user to close and reopen it. This is a valid, neutral one-pixel JPEG and
# is normally visible for less than one frame interval.
_WAITING_FOR_LIVE_FRAME = b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIf"
    "IiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7"
    "Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAABAAEDASIAAhEB"
    "AxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAA"
    "AAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AIyAD//Z"
)


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
    def start_requested(self) -> bool:
        commands = getattr(self.coordinator.device, "commands", {})
        return any(
            getattr(command, "type", None) == "start_camera_session"
            and getattr(command, "state", None) in {"pending", "delivered"}
            and getattr(command, "payload", {}).get("camera_id") == self.key
            for command in commands.values()
        )

    @property
    def supported_features(self) -> CameraEntityFeature:
        return CameraEntityFeature.ON_OFF

    async def async_camera_image(self, width=None, height=None):
        if live := self.coordinator.get_live_frame(self.key):
            return live
        if self.is_on or self.start_requested:
            return _WAITING_FOR_LIVE_FRAME
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
