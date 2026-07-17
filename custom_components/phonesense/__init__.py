from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .api import PhoneSenseApiView, PhoneSenseCommandResultView, PhoneSenseDeviceApiView, PhoneSenseLiveMjpegView, PhoneSenseMediaView, PhoneSenseRecordingCollectionView, PhoneSenseRecordingView
from .bluetooth import async_register_remote_scanner, scanner_address
from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN, PLATFORMS, normalize_device_name
from .coordinator import PhoneSenseCoordinator
from .models import Capability, Command, PhoneSenseDevice, StreamState
from .storage import PhoneSenseStore
from .repairs import update_device_issues
from .entity import control_supported

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {"coordinators": {}, "scanners": {}, "store": PhoneSenseStore(hass), "views_registered": False})
    hass.data[DOMAIN].setdefault("coordinators", {})
    hass.data[DOMAIN].setdefault("scanners", {})
    await hass.data[DOMAIN]["store"].async_load()
    if not hass.data[DOMAIN]["views_registered"]:
        hass.http.register_view(PhoneSenseApiView)
        # Register exact/specific routes before the generic device action route
        # so aiohttp does not consume `/media` as an unknown `{action}`.
        hass.http.register_view(PhoneSenseMediaView)
        hass.http.register_view(PhoneSenseRecordingCollectionView)
        hass.http.register_view(PhoneSenseRecordingView)
        hass.http.register_view(PhoneSenseLiveMjpegView)
        hass.http.register_view(PhoneSenseCommandResultView)
        hass.http.register_view(PhoneSenseDeviceApiView)
        hass.data[DOMAIN]["views_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await async_setup(hass, {})
    _remove_legacy_motion_entity(hass, entry)
    _remove_legacy_action_entities(hass, entry)
    _remove_legacy_camera_selector(hass, entry)
    _remove_legacy_global_camera_settings(hass, entry)
    _remove_legacy_ambiguous_camera_actions(hass, entry)
    stored = hass.data[DOMAIN]["store"].data.get("devices", {}).get(entry.data[CONF_DEVICE_ID], {})
    platform = stored.get("platform", "unknown")
    device_name = normalize_device_name(entry.data[CONF_DEVICE_NAME], platform)
    if device_name != entry.data[CONF_DEVICE_NAME]:
        hass.config_entries.async_update_entry(
            entry,
            title=device_name if entry.title == entry.data[CONF_DEVICE_NAME] else entry.title,
            data={**entry.data, CONF_DEVICE_NAME: device_name},
        )
    device = PhoneSenseDevice(entry.data[CONF_DEVICE_ID], device_name, platform, stored.get("os_version", "unknown"), stored.get("app_version", "unknown"))
    device.capabilities = {key: Capability(key, value.get("status", "unsupported"), value.get("metadata", {})) for key, value in stored.get("capabilities", {}).items()}
    device.streams = {key: StreamState(key, value.get("value"), value.get("unit"), value.get("kind", "state"), value.get("observed_at"), None, value.get("quality", {}), value.get("last_sequence", -1)) for key, value in stored.get("streams", {}).items()}
    device.health = stored.get("health", {})
    dedup_keys = stored.get("dedup_keys", [])
    if isinstance(dedup_keys, list):
        for item in dedup_keys:
            if not (isinstance(item, list) and len(item) == 3 and isinstance(item[0], str) and isinstance(item[1], str)):
                continue
            try:
                device.seen_order.append((item[0], item[1], int(item[2])))
            except (TypeError, ValueError):
                continue
        device.seen_keys = set(device.seen_order)
    if stored.get("last_seen"):
        device.last_seen = datetime.fromisoformat(stored["last_seen"].replace("Z", "+00:00"))
    device.commands = {
        key: Command(
            command_id=key,
            type=value.get("type", "ping"),
            payload=value.get("payload", {}),
            issued_at=value.get("issued_at", ""),
            expires_at=value.get("expires_at"),
            requires_local_arming=value.get("requires_local_arming", False),
            state=value.get("state", "pending"),
            result=value.get("result"),
        )
        for key, value in stored.get("commands", {}).items()
    }
    _remove_unsupported_control_entities(hass, entry, device)
    coordinator = PhoneSenseCoordinator(hass, hass.data[DOMAIN]["store"], device)
    hass.data[DOMAIN]["coordinators"][device.device_id] = coordinator
    update_device_issues(hass, device)
    device_registry = dr.async_get(hass)
    registry_device = device_registry.async_get_device(identifiers={(DOMAIN, device.device_id)})
    if registry_device and registry_device.name == "PhoneSense Ios" and registry_device.name_by_user is None:
        # A legacy generated name can be reasserted by already-registered
        # entity device-info during startup. Migrate that exact generated value
        # through name_by_user so it remains stable; genuine user names never
        # enter this branch.
        device_registry.async_update_device(registry_device.id, name_by_user=device_name)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device.device_id)},
        connections={(dr.CONNECTION_BLUETOOTH, scanner_address(device.device_id))},
        name=device.name,
        manufacturer="PhoneSense",
        model=f"{device.platform} sensor node",
        sw_version=device.app_version,
    )
    scanner, unregister, scanner_cleanup = async_register_remote_scanner(hass, device.device_id, coordinator)
    hass.data[DOMAIN]["scanners"][device.device_id] = (scanner, unregister, scanner_cleanup)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove entities superseded by numeric sensors and persistent controls."""
    if entry.version < 2:
        _remove_legacy_motion_entity(hass, entry)
    if entry.version < 3:
        _remove_legacy_action_entities(hass, entry)
    if entry.version < 4:
        _remove_legacy_camera_selector(hass, entry)
    if entry.version < 5:
        _remove_legacy_global_camera_settings(hass, entry)
    if entry.version < 6:
        _remove_legacy_ambiguous_camera_actions(hass, entry)
        hass.config_entries.async_update_entry(entry, version=6)
    return True


def _remove_legacy_motion_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Idempotently remove the superseded Boolean motion registry entry."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    registry = er.async_get(hass)
    legacy_entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{device_id}_motion_state")
    if legacy_entity_id:
        registry.async_remove(legacy_entity_id)


def _remove_legacy_action_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove one-shot controls replaced by module and per-camera switches."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    registry = er.async_get(hass)
    for key in (
        "start_camera_session",
        "stop_camera_session",
        "start_audio_session",
        "stop_audio_session",
        "vibrate",
    ):
        unique_id = f"{device_id}_{key}"
        entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)


def _remove_legacy_camera_selector(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the ambiguous dropdown superseded by one switch per lens."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("select", DOMAIN, f"{device_id}_active_camera")
    if entity_id:
        registry.async_remove(entity_id)


def _remove_legacy_global_camera_settings(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove ambiguous settings that were shared by every physical camera."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    registry = er.async_get(hass)
    settings = {
        "number": (
            "quality", "frame_rate", "focus_distance_percent",
            "exposure_compensation_percent", "iso_percent", "manual_exposure_percent",
        ),
        "select": ("resolution", "photo_resolution", "white_balance", "color_effect", "antibanding"),
        "switch": ("autofocus_hold", "night_mode", "manual_sensor"),
    }
    for platform, keys in settings.items():
        for key in keys:
            entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{device_id}_camera_setting_{key}")
            if entity_id:
                registry.async_remove(entity_id)


def _remove_legacy_ambiguous_camera_actions(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove global controls replaced by explicit per-camera controls."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return
    registry = er.async_get(hass)
    for platform, key in (
        ("button", "flush_queue"),
        ("button", "capture_snapshot"),
        ("switch", "camera_local_recording"),
        ("select", "camera_recording_segment_length"),
    ):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{device_id}_{key}")
        if entity_id:
            registry.async_remove(entity_id)


def _remove_unsupported_control_entities(hass: HomeAssistant, entry: ConfigEntry, device: PhoneSenseDevice) -> None:
    """Remove registry rows for controls the phone cannot implement."""
    registry = er.async_get(hass)
    controls = (
        ("switch", "location", "location"),
        ("switch", "motion", "motion"),
        ("switch", "network", "network"),
        ("switch", "ble_proxy", "ble_proxy"),
        ("switch", "camera", "camera"),
        ("switch", "audio", "audio"),
        ("switch", "actuator_vibration", "actuator.vibration"),
        ("light", "actuator_flashlight", "actuator.flashlight"),
        ("light", "display_screen", "display.screen"),
        ("media_player", "media_playback", "media.playback"),
        ("number", "location_interval", "location"),
        ("number", "motion_publish_interval", "motion"),
        ("button", "capture_snapshot", "camera"),
    )
    for platform, unique_key, capability_key in controls:
        if control_supported(device, capability_key):
            continue
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{device.device_id}_{unique_key}")
        if entity_id:
            registry.async_remove(entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    device_id = entry.data[CONF_DEVICE_ID]
    scanner_state = hass.data[DOMAIN].get("scanners", {}).pop(device_id, None)
    if scanner_state:
        _, unregister, scanner_cleanup = scanner_state
        unregister()
        scanner_cleanup()
    hass.data[DOMAIN]["coordinators"].pop(device_id, None)
    return unloaded
