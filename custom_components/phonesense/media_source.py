from __future__ import annotations

from datetime import datetime

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_source import BrowseMediaSource, MediaSource, MediaSourceItem, PlayMedia
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.core import HomeAssistant

from .api import _list_recordings, _media_directory
from .const import API_BASE, DOMAIN


async def async_get_media_source(hass: HomeAssistant) -> "PhoneSenseMediaSource":
    return PhoneSenseMediaSource(hass)


class PhoneSenseMediaSource(MediaSource):
    name = "PhoneSense recordings"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        parts = item.identifier.split("/")
        if len(parts) != 3:
            raise Unresolvable("Select a recording first.")
        device_id, camera_id, recording_id = parts
        recordings = await self._recordings(device_id)
        if not any(value.get("media_id") == recording_id and value.get("camera_id") == camera_id for value in recordings):
            raise Unresolvable("Recording not found.")
        path = _media_directory(self.hass, device_id)
        recording_path = path / f"{recording_id}.mp4" if path else None
        if recording_path is None or not recording_path.is_file():
            raise Unresolvable("Recording not found.")
        return PlayMedia(
            f"{API_BASE}/devices/{device_id}/recordings/{recording_id}",
            "video/mp4",
            path=recording_path,
        )

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        # Home Assistant represents the source root with a null identifier.
        parts = [part for part in (item.identifier or "").split("/") if part]
        if len(parts) > 2:
            raise BrowseError("Recording folders cannot be expanded.")
        if not parts:
            return await self._browse_root()
        if len(parts) == 1:
            return await self._browse_device(parts[0])
        return await self._browse_camera(parts[0], parts[1])

    async def _recordings(self, device_id: str) -> list[dict]:
        if device_id not in self.hass.data.get(DOMAIN, {}).get("coordinators", {}):
            return []
        directory = _media_directory(self.hass, device_id)
        if directory is None:
            return []
        return await self.hass.async_add_executor_job(_list_recordings, directory)

    async def _browse_root(self) -> BrowseMediaSource:
        base = self._directory("", self.name, MediaClass.APP)
        children = []
        for device_id, coordinator in sorted(self.hass.data.get(DOMAIN, {}).get("coordinators", {}).items(), key=lambda item: item[1].device.name):
            if await self._recordings(device_id):
                children.append(self._directory(device_id, coordinator.device.name))
        base.children = children
        return base

    async def _browse_device(self, device_id: str) -> BrowseMediaSource:
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            raise BrowseError("PhoneSense device not found.")
        recordings = await self._recordings(device_id)
        base = self._directory(device_id, coordinator.device.name)
        camera_ids = sorted({str(value.get("camera_id")) for value in recordings if value.get("camera_id")})
        base.children = [self._directory(f"{device_id}/{camera_id}", camera_id.replace("camera.", "Camera ").replace(".", " ").title()) for camera_id in camera_ids]
        return base

    async def _browse_camera(self, device_id: str, camera_id: str) -> BrowseMediaSource:
        recordings = [value for value in await self._recordings(device_id) if value.get("camera_id") == camera_id]
        if not recordings and device_id not in self.hass.data.get(DOMAIN, {}).get("coordinators", {}):
            raise BrowseError("PhoneSense device not found.")
        base = self._directory(f"{device_id}/{camera_id}", camera_id.replace("camera.", "Camera ").replace(".", " ").title())
        base.children = [self._recording_item(device_id, camera_id, value) for value in recordings]
        return base

    def _directory(self, identifier: str, title: str, media_class: MediaClass = MediaClass.DIRECTORY) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=media_class,
            media_content_type=MediaType.APP if media_class == MediaClass.APP else None,
            title=title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
        )

    def _recording_item(self, device_id: str, camera_id: str, value: dict) -> BrowseMediaSource:
        observed_at = str(value.get("observed_at", ""))
        try:
            timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = observed_at or str(value.get("media_id", "Recording"))
        duration_seconds = max(0, int(value.get("duration_ms", 0)) // 1000)
        title = f"{timestamp} ({duration_seconds // 60}:{duration_seconds % 60:02d})"
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{device_id}/{camera_id}/{value['media_id']}",
            media_class=MediaClass.VIDEO,
            media_content_type="video/mp4",
            title=title,
            can_play=True,
            can_expand=False,
        )
