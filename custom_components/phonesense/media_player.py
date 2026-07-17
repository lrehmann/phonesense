from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.components.media_source import async_resolve_media, is_media_source_id
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, control_supported


class PhoneSenseMediaPlayer(PhoneSenseEntity, MediaPlayerEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "media.playback")
        self._attr_name = "Speaker"
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )

    @property
    def state(self) -> MediaPlayerState:
        value = self.coordinator.device.health.get("media_player", {}).get("state", "idle")
        return {
            "playing": MediaPlayerState.PLAYING,
            "paused": MediaPlayerState.PAUSED,
            "buffering": MediaPlayerState.BUFFERING,
        }.get(value, MediaPlayerState.IDLE)

    @property
    def volume_level(self) -> float:
        return float(self.coordinator.device.health.get("media_player", {}).get("volume", 1.0))

    @property
    def is_volume_muted(self) -> bool:
        return bool(self.coordinator.device.health.get("media_player", {}).get("muted", False))

    @property
    def media_title(self) -> str | None:
        return self.coordinator.device.health.get("media_player", {}).get("title")

    @property
    def media_content_id(self) -> str | None:
        return self.coordinator.device.health.get("media_player", {}).get("content_id")

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        title = kwargs.get("title") or media_id.rsplit("/", 1)[-1]
        if is_media_source_id(media_id):
            resolved = await async_resolve_media(self.hass, media_id, self.entity_id)
            media_id = resolved.url
            media_type = resolved.mime_type or media_type
        url = async_process_play_media_url(self.hass, media_id)
        self.coordinator.device.health.setdefault("media_player", {}).update({"state": "buffering", "title": title, "content_id": url})
        await self.coordinator.async_queue_command("play_media", {"url": url, "content_type": media_type, "title": title})

    async def async_media_play(self) -> None:
        self.coordinator.device.health.setdefault("media_player", {})["state"] = "playing"
        await self.coordinator.async_queue_command("resume_media")

    async def async_media_pause(self) -> None:
        self.coordinator.device.health.setdefault("media_player", {})["state"] = "paused"
        await self.coordinator.async_queue_command("pause_media")

    async def async_media_stop(self) -> None:
        self.coordinator.device.health.setdefault("media_player", {})["state"] = "idle"
        await self.coordinator.async_queue_command("stop_media")

    async def async_set_volume_level(self, volume: float) -> None:
        self.coordinator.device.health.setdefault("media_player", {})["volume"] = volume
        await self.coordinator.async_queue_command("set_media_volume", {"volume": volume})

    async def async_mute_volume(self, mute: bool) -> None:
        self.coordinator.device.health.setdefault("media_player", {})["muted"] = mute
        await self.coordinator.async_queue_command("set_media_muted", {"muted": mute})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    async_add_entities([PhoneSenseMediaPlayer(coordinator)] if control_supported(coordinator.device, "media.playback") else [])
