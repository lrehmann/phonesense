from __future__ import annotations

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, control_supported


class PhoneSenseFlashlight(PhoneSenseEntity, LightEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "actuator.flashlight")
        self._attr_name = "Flashlight"
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.device.health.get("actuators", {}).get("flashlight", False))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("actuators", {})["flashlight"] = True
        await self.coordinator.async_queue_command("set_flashlight", {"enabled": True})

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.device.health.setdefault("actuators", {})["flashlight"] = False
        await self.coordinator.async_queue_command("set_flashlight", {"enabled": False})


class PhoneSenseScreenLight(PhoneSenseEntity, LightEntity):
    def __init__(self, coordinator: PhoneSenseCoordinator) -> None:
        PhoneSenseEntity.__init__(self, coordinator, "display.screen")
        self._attr_name = "Screen"
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.device.health.get("display", {}).get("enabled", False))

    @property
    def brightness(self) -> int:
        return max(1, min(255, int(self.coordinator.device.health.get("display", {}).get("brightness", 255))))

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        value = self.coordinator.device.health.get("display", {}).get("rgb", [255, 255, 255])
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return (255, 255, 255)
        return tuple(max(0, min(255, int(component))) for component in value[:3])

    async def async_turn_on(self, **kwargs) -> None:
        brightness = max(1, min(255, int(kwargs.get(ATTR_BRIGHTNESS, self.brightness))))
        rgb = kwargs.get(ATTR_RGB_COLOR, self.rgb_color)
        rgb = tuple(max(0, min(255, int(component))) for component in rgb[:3])
        state = {"enabled": True, "brightness": brightness, "rgb": list(rgb)}
        self.coordinator.device.health["display"] = state
        await self.coordinator.async_queue_command("set_display", {
            "enabled": True,
            "brightness": brightness,
            "rgb": list(rgb),
        })

    async def async_turn_off(self, **kwargs) -> None:
        state = self.coordinator.device.health.setdefault("display", {})
        state.update({"enabled": False, "brightness": self.brightness, "rgb": list(self.rgb_color)})
        await self.coordinator.async_queue_command("set_display", {"enabled": False})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    entities = []
    if control_supported(coordinator.device, "actuator.flashlight"):
        entities.append(PhoneSenseFlashlight(coordinator))
    if control_supported(coordinator.device, "display.screen"):
        entities.append(PhoneSenseScreenLight(coordinator))
    async_add_entities(entities)
