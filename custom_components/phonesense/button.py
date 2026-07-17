from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .coordinator import PhoneSenseCoordinator
from .entity import PhoneSenseEntity, camera_device_info, control_supported


class PhoneSenseButton(PhoneSenseEntity, ButtonEntity):
    _require_runtime_support = False

    def __init__(self, coordinator: PhoneSenseCoordinator, key: str, name: str) -> None:
        PhoneSenseEntity.__init__(self, coordinator, key)
        self._attr_name = name

    async def async_press(self) -> None:
        payload = {"duration_ms": 500, "amplitude": 255} if self.key == "vibrate" else None
        await self.coordinator.async_queue_command(self.key, payload, requires_local_arming=False)


class PhoneSenseCameraSnapshotButton(PhoneSenseButton):
    def __init__(self, coordinator: PhoneSenseCoordinator, camera_id: str, metadata: dict) -> None:
        PhoneSenseButton.__init__(self, coordinator, f"capture_snapshot_{camera_id.replace('.', '_')}", "Take snapshot (phone must be armed)")
        self.camera_id = camera_id
        self._attr_device_info = camera_device_info(coordinator, camera_id, metadata)

    async def async_press(self) -> None:
        await self.coordinator.async_queue_command(
            "capture_snapshot",
            {"camera_id": self.camera_id},
            requires_local_arming=True,
        )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data["phonesense"]["coordinators"][entry.data["device_id"]]
    rescan = PhoneSenseButton(coordinator, "refresh_capabilities", "Rescan phone hardware")
    rescan._attr_entity_category = EntityCategory.DIAGNOSTIC
    entities = [rescan]
    if control_supported(coordinator.device, "camera"):
        entities.extend(
            PhoneSenseCameraSnapshotButton(coordinator, camera_id, capability.metadata)
            for camera_id, capability in coordinator.device.capabilities.items()
            if camera_id.startswith("camera.")
            and capability.status != "unsupported"
            and capability.metadata.get("snapshot") is True
        )
    async_add_entities(entities)
