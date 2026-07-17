"""Remote Bluetooth scanner fed by PhoneSense Android advertisements."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from bleak.backends.device import BLEDevice
from habluetooth import BaseHaRemoteScanner, BluetoothServiceInfoBleak
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .entity import module_enabled


def scanner_address(device_id: str) -> str:
    """Return a stable locally administered MAC-shaped scanner address."""
    address = bytearray(hashlib.sha256(device_id.encode()).digest()[:6])
    address[0] = (address[0] | 0x02) & 0xFE
    return ":".join(f"{value:02X}" for value in address)


def _hex_bytes(value: Any) -> bytes:
    if not isinstance(value, str):
        return b""
    try:
        return bytes.fromhex(value)
    except ValueError:
        return b""


class PhoneSenseRemoteScanner(BaseHaRemoteScanner):
    """A passive remote scanner represented by one enrolled PhoneSense phone."""

    def __init__(self, hass: HomeAssistant, device_id: str, coordinator: Any) -> None:
        self.device_id = device_id
        self.coordinator = coordinator
        self._advertisement_callback = bluetooth.async_get_advertisement_callback(hass)
        source = scanner_address(device_id)
        super().__init__(source=source, adapter=source, connectable=False)

    def async_on_advertisement(self, payload: dict[str, Any]) -> bool:
        """Forward one phone-proxied advertisement into HA's Bluetooth manager."""
        if not module_enabled(self.coordinator, "ble_proxy"):
            return False
        address = payload.get("address")
        rssi = payload.get("rssi")
        if not isinstance(address, str) or not address or not isinstance(rssi, int):
            return False

        name = payload.get("name") or address
        manufacturer_data: dict[int, bytes] = {}
        raw_manufacturer_data = payload.get("manufacturer_data")
        if not isinstance(raw_manufacturer_data, dict):
            raw_manufacturer_data = {}
        for key, value in raw_manufacturer_data.items():
            try:
                manufacturer_data[int(key)] = _hex_bytes(value)
            except (TypeError, ValueError):
                continue
        service_data: dict[str, bytes] = {}
        raw_service_data = payload.get("service_data")
        if not isinstance(raw_service_data, dict):
            raw_service_data = {}
        for key, value in raw_service_data.items():
            if isinstance(key, str):
                service_data[key] = _hex_bytes(value)
        service_uuids = [item for item in payload.get("service_uuids", []) if isinstance(item, str)]
        source = self.source
        device = BLEDevice(address, name, {"source": source}, rssi=rssi)
        info = BluetoothServiceInfoBleak(
            name=name,
            address=address,
            rssi=rssi,
            manufacturer_data=manufacturer_data,
            service_data=service_data,
            service_uuids=service_uuids,
            source=source,
            device=device,
            advertisement=None,
            connectable=bool(payload.get("connectable", False)),
            time=time.monotonic(),
            tx_power=payload.get("tx_power") if isinstance(payload.get("tx_power"), int) else None,
            raw=None,
        )
        self._advertisement_callback(info)
        return True


def async_register_remote_scanner(hass: HomeAssistant, device_id: str, coordinator: Any) -> tuple[PhoneSenseRemoteScanner, Any, Any]:
    """Create and register a scanner, returning scanner and cleanup callbacks."""
    scanner = PhoneSenseRemoteScanner(hass, device_id, coordinator)
    scanner_cleanup = scanner.async_setup()
    unregister = bluetooth.async_register_scanner(
        hass,
        scanner,
        connection_slots=0,
        source_domain="phonesense",
    )
    return scanner, unregister, scanner_cleanup
