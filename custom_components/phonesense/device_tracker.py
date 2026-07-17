from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, entity_supported


class PhoneSenseTracker(PhoneSenseEntity, TrackerEntity):
    _attr_name = "Location"

    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        super().__init__(coordinator, "location.gps")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self):
        value = self.native_value or {}
        return value.get("latitude") if isinstance(value, dict) else None

    @property
    def longitude(self):
        value = self.native_value or {}
        return value.get("longitude") if isinstance(value, dict) else None

    @property
    def extra_state_attributes(self):
        value = self.native_value or {}
        return value if isinstance(value, dict) else None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    if entity_supported(coordinator, "location.gps", "location.gps"):
        async_add_entities([PhoneSenseTracker(coordinator)])
