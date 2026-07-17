from __future__ import annotations

from typing import Any
from uuid import uuid4

from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


class PhoneSenseStore:
    """Small bounded persistence layer for capabilities, latest state, and sequence watermarks."""

    def __init__(self, hass: Any) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = {"instance_id": str(uuid4()), "devices": {}}

    async def async_load(self) -> None:
        self.data = await self._store.async_load() or {"instance_id": str(uuid4()), "devices": {}}
        self.data.setdefault("instance_id", str(uuid4()))
        self.data.setdefault("devices", {})

    async def async_save(self) -> None:
        await self._store.async_save(self.data)
