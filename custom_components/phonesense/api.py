from __future__ import annotations

from http import HTTPStatus
import asyncio
import base64
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from aiohttp import web
from homeassistant import config_entries
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import API_BASE, CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN, default_device_name

_SAFE_DEVICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SUPPORTED_PROTOCOLS = ("1.0",)
_SAFE_MEDIA_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _protocol_error(payload: dict[str, Any]) -> str | None:
    """Return a structured compatibility error for a client payload."""
    value = payload.get("protocol_version")
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+", value):
        return "protocol_version_required"
    if value.split(".", 1)[0] != _SUPPORTED_PROTOCOLS[-1].split(".", 1)[0]:
        return "protocol_major_mismatch"
    return None


def _protocol_failure(error: str) -> web.Response:
    return web.json_response({
        "error": error,
        "required_upgrade": True,
        "server_supported": list(_SUPPORTED_PROTOCOLS),
    }, status=HTTPStatus.UPGRADE_REQUIRED)


def _media_quota_bytes(coordinator: Any) -> int:
    """Return the effective server-side media quota for one device."""
    try:
        value = int(
            coordinator.device.health.get("effective_configuration", {})
            .get("retention", {})
            .get("media_bytes", 250 * 1024 * 1024)
        )
    except (AttributeError, TypeError, ValueError):
        value = 250 * 1024 * 1024
    return max(1 * 1024 * 1024, min(524 * 1024 * 1024, value))


def _json(request: web.Request) -> dict[str, Any]:
    return request.get("_json", {})


def _media_directory(hass: HomeAssistant, device_id: str) -> Path | None:
    """Return a media directory without allowing route data to escape storage."""
    if not _SAFE_DEVICE_ID.fullmatch(device_id):
        return None
    return Path(hass.config.path(".storage", "phonesense_media", device_id))


def _finalize_recording_upload(temporary: Path, path: Path, metadata_path: Path, metadata: dict[str, Any]) -> None:
    """Atomically publish a completed recording and its metadata off the event loop."""
    temporary.replace(path)
    metadata_path.write_text(json.dumps(metadata, separators=(",", ":")))


def _remove_file(path: Path) -> None:
    """Remove a temporary file off the event loop."""
    path.unlink(missing_ok=True)


def _store_media_file(
    media_dir: Path,
    requested_media_id: str | None,
    media_id: str,
    suffix: str,
    raw: bytes,
    quota_bytes: int,
) -> tuple[Path, bool]:
    """Store media atomically; callers run this filesystem work in an executor."""
    media_dir.mkdir(parents=True, exist_ok=True)
    if requested_media_id:
        existing_match = next(
            (path for path in media_dir.glob(f"{requested_media_id}.*") if path.suffix in {".jpg", ".heic", ".png"}),
            None,
        )
        if existing_match is not None:
            return existing_match, True
    existing = sorted(
        (path for path in media_dir.iterdir() if path.is_file() and not path.name.startswith(".")),
        key=lambda path: path.stat().st_mtime,
    )
    retained_bytes = sum(path.stat().st_size for path in existing)
    while retained_bytes + len(raw) > quota_bytes and existing:
        old = existing.pop(0)
        retained_bytes -= old.stat().st_size
        old.unlink(missing_ok=True)
        (media_dir / f".{old.stem}.json").unlink(missing_ok=True)
    path = media_dir / f"{media_id}{suffix}"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return path, False


def _recording_metadata(path: Path) -> dict[str, Any] | None:
    metadata_path = path.parent / f".{path.stem}.json"
    try:
        value = json.loads(metadata_path.read_text())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    return {**value, "media_id": path.stem, "bytes": path.stat().st_size}


def _list_recordings(media_dir: Path) -> list[dict[str, Any]]:
    if not media_dir.is_dir():
        return []
    values = [metadata for path in media_dir.glob("*.mp4") if (metadata := _recording_metadata(path)) is not None]
    return sorted(values, key=lambda item: str(item.get("observed_at", "")), reverse=True)


def _reserve_recording_space(media_dir: Path, recording_id: str, size: int, quota_bytes: int) -> tuple[Path, bool]:
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / f"{recording_id}.mp4"
    if path.is_file():
        return path, True
    existing = sorted(
        (item for item in media_dir.iterdir() if item.is_file() and not item.name.startswith(".") and item.suffix in {".jpg", ".heic", ".png", ".mp4"}),
        key=lambda item: item.stat().st_mtime,
    )
    retained_bytes = sum(item.stat().st_size for item in existing)
    while retained_bytes + size > quota_bytes and existing:
        old = existing.pop(0)
        retained_bytes -= old.stat().st_size
        old.unlink(missing_ok=True)
        (media_dir / f".{old.stem}.json").unlink(missing_ok=True)
    return path, False


class PhoneSenseApiView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/{{action}}"
    name = "api:phonesense:action"

    async def post(self, request: web.Request, action: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        try:
            payload = await request.json()
        except ValueError:
            return self.json_message("invalid_json", HTTPStatus.BAD_REQUEST)
        if action == "register":
            return await _register(hass, payload)
        return self.json_message("unknown_action", HTTPStatus.NOT_FOUND)


class PhoneSenseDeviceApiView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/devices/{{device_id}}/{{action}}"
    name = "api:phonesense:device-action"

    async def post(self, request: web.Request, device_id: str, action: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            return self.json_message("unknown_device", HTTPStatus.NOT_FOUND)
        try:
            payload = await request.json()
        except ValueError:
            return self.json_message("invalid_json", HTTPStatus.BAD_REQUEST)
        if action == "capabilities":
            if payload.get("schema_version") != 1:
                return self.json_message("unsupported_schema_version", HTTPStatus.BAD_REQUEST)
            await coordinator.async_set_capabilities(payload)
            await hass.async_block_till_done()
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.data.get("device_id") == device_id:
                    await hass.config_entries.async_reload(entry.entry_id)
                    break
            return self.json({"ok": True, "device_id": device_id})
        if action == "batch":
            if payload.get("schema_version") != 1:
                return self.json_message("unsupported_schema_version", HTTPStatus.BAD_REQUEST)
            protocol_error = _protocol_error(payload)
            if protocol_error:
                coordinator.device.health["protocol_error"] = protocol_error
                coordinator._touch()
                return _protocol_failure(protocol_error)
            if payload.get("device_id") != device_id:
                return self.json_message("device_mismatch", HTTPStatus.BAD_REQUEST)
            coordinator.device.health.pop("protocol_error", None)
            return self.json(await coordinator.async_ingest_batch(payload))
        if action == "health":
            await coordinator.async_set_health(payload)
            return self.json({"ok": True, "device_id": device_id})
        if action == "live-frame":
            try:
                camera_id = payload["camera_id"]
                sequence = int(payload["sequence"])
                raw = base64.b64decode(payload["data_base64"], validate=True)
            except (ValueError, KeyError, TypeError):
                return self.json_message("invalid_live_frame", HTTPStatus.BAD_REQUEST)
            capability = coordinator.device.capabilities.get(camera_id) if isinstance(camera_id, str) else None
            if (
                not isinstance(camera_id, str)
                or not camera_id.startswith("camera.")
                or capability is None
                or capability.status != "available"
            ):
                return self.json_message("unknown_camera", HTTPStatus.BAD_REQUEST)
            if payload.get("mime_type", "image/jpeg") != "image/jpeg":
                return self.json_message("unsupported_media_type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            if sequence < 0 or not raw or len(raw) > 2 * 1024 * 1024:
                return self.json_message("live_frame_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            accepted = coordinator.set_live_frame(camera_id, raw, sequence, payload.get("observed_at"))
            if accepted:
                coordinator.mark_live_presence()
            return self.json({"ok": True, "camera_id": camera_id, "sequence": sequence, "accepted": accepted})
        if action == "commands":
            return self.json({"ok": True, "device_id": device_id})
        return self.json_message("unknown_action", HTTPStatus.NOT_FOUND)

    async def get(self, request: web.Request, device_id: str, action: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        result = await _commands_get(hass, device_id) if action == "commands" else None
        if result is None:
            return self.json_message("unknown_device" if action == "commands" else "unknown_action", HTTPStatus.NOT_FOUND)
        return self.json(result)


class PhoneSenseCommandResultView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/devices/{{device_id}}/commands/{{command_id}}/result"
    name = "api:phonesense:command-result"

    async def post(self, request: web.Request, device_id: str, command_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            return self.json_message("unknown_device", HTTPStatus.NOT_FOUND)
        try:
            payload = await request.json()
        except ValueError:
            return self.json_message("invalid_json", HTTPStatus.BAD_REQUEST)
        if not await coordinator.async_set_command_result(command_id, payload):
            return self.json_message("unknown_command", HTTPStatus.NOT_FOUND)
        return self.json({"ok": True, "command_id": command_id})


class PhoneSenseMediaView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/devices/{{device_id}}/media"
    name = "api:phonesense:media"

    async def post(self, request: web.Request, device_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            return self.json_message("unknown_device", HTTPStatus.NOT_FOUND)
        try:
            payload = await request.json()
            raw = base64.b64decode(payload["data_base64"], validate=True)
        except (ValueError, KeyError, TypeError):
            return self.json_message("invalid_media", HTTPStatus.BAD_REQUEST)
        if not raw or len(raw) > 8 * 1024 * 1024:
            return self.json_message("media_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        mime_type = payload.get("mime_type", "image/jpeg")
        if mime_type not in {"image/jpeg", "image/heic", "image/png"}:
            return self.json_message("unsupported_media_type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        camera_id = payload.get("camera_id", "camera.rear.0")
        media_dir = _media_directory(hass, device_id)
        if media_dir is None:
            return self.json_message("invalid_device_id", HTTPStatus.BAD_REQUEST)
        requested_media_id = payload.get("media_id")
        if requested_media_id is not None and (not isinstance(requested_media_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", requested_media_id)):
            return self.json_message("invalid_media_id", HTTPStatus.BAD_REQUEST)
        media_id = requested_media_id or str(uuid4())
        quota_bytes = _media_quota_bytes(coordinator)
        if len(raw) > quota_bytes:
            return self.json_message("media_exceeds_configured_quota", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        suffix = ".jpg" if mime_type == "image/jpeg" else ".png" if mime_type == "image/png" else ".heic"
        path, deduplicated = await hass.async_add_executor_job(
            _store_media_file,
            media_dir,
            requested_media_id,
            media_id,
            suffix,
            raw,
            quota_bytes,
        )
        if deduplicated:
            return self.json({"ok": True, "media_id": media_id, "camera_id": camera_id, "deduplicated": True})
        coordinator.device.health.setdefault("snapshots", {})[camera_id] = {"media_id": media_id, "path": str(path), "mime_type": mime_type, "observed_at": payload.get("observed_at")}
        coordinator._touch()
        return self.json({"ok": True, "media_id": media_id, "camera_id": camera_id})


class PhoneSenseRecordingCollectionView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/devices/{{device_id}}/recordings"
    name = "api:phonesense:recordings"

    async def get(self, request: web.Request, device_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        if device_id not in hass.data.get(DOMAIN, {}).get("coordinators", {}):
            return self.json_message("unknown_device", HTTPStatus.NOT_FOUND)
        media_dir = _media_directory(hass, device_id)
        if media_dir is None:
            return self.json_message("invalid_device_id", HTTPStatus.BAD_REQUEST)
        recordings = await hass.async_add_executor_job(_list_recordings, media_dir)
        return self.json({"device_id": device_id, "recordings": recordings})


class PhoneSenseRecordingView(HomeAssistantView):
    requires_auth = True
    url = f"{API_BASE}/devices/{{device_id}}/recordings/{{recording_id}}"
    name = "api:phonesense:recording"

    async def post(self, request: web.Request, device_id: str, recording_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            return self.json_message("unknown_device", HTTPStatus.NOT_FOUND)
        if not _SAFE_MEDIA_ID.fullmatch(recording_id):
            return self.json_message("invalid_recording_id", HTTPStatus.BAD_REQUEST)
        media_dir = _media_directory(hass, device_id)
        if media_dir is None:
            return self.json_message("invalid_device_id", HTTPStatus.BAD_REQUEST)
        try:
            size = int(request.headers.get("Content-Length", ""))
            duration_ms = int(request.headers.get("X-PhoneSense-Duration-Ms", "0"))
            segment_minutes = int(request.headers.get("X-PhoneSense-Segment-Minutes", "0"))
        except ValueError:
            return self.json_message("invalid_recording_metadata", HTTPStatus.BAD_REQUEST)
        camera_id = request.headers.get("X-PhoneSense-Camera-Id", "")
        observed_at = request.headers.get("X-PhoneSense-Observed-At", "")
        capability = coordinator.device.capabilities.get(camera_id)
        quota_bytes = _media_quota_bytes(coordinator)
        if request.content_type != "video/mp4":
            return self.json_message("unsupported_media_type", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if size <= 0 or size > quota_bytes:
            return self.json_message("recording_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if capability is None or capability.status != "available" or not camera_id.startswith("camera."):
            return self.json_message("unknown_camera", HTTPStatus.BAD_REQUEST)
        if not observed_at or len(observed_at) > 64 or segment_minutes not in {1, 5, 10} or duration_ms < 0:
            return self.json_message("invalid_recording_metadata", HTTPStatus.BAD_REQUEST)
        path, deduplicated = await hass.async_add_executor_job(_reserve_recording_space, media_dir, recording_id, size, quota_bytes)
        if deduplicated:
            return self.json({"ok": True, "media_id": recording_id, "deduplicated": True})
        request._client_max_size = quota_bytes  # noqa: SLF001
        temporary = media_dir / f".{recording_id}.upload"
        written = 0
        output = None
        try:
            output = await hass.async_add_executor_job(temporary.open, "wb")
            try:
                async for chunk in request.content.iter_chunked(256 * 1024):
                    written += len(chunk)
                    if written > size or written > quota_bytes:
                        raise web.HTTPRequestEntityTooLarge(max_size=quota_bytes, actual_size=written)
                    await hass.async_add_executor_job(output.write, chunk)
            finally:
                await hass.async_add_executor_job(output.close)
                output = None
            if written != size:
                await hass.async_add_executor_job(_remove_file, temporary)
                return self.json_message("recording_size_mismatch", HTTPStatus.BAD_REQUEST)
            metadata = {
                "camera_id": camera_id,
                "observed_at": observed_at,
                "duration_ms": duration_ms,
                "segment_minutes": segment_minutes,
                "mime_type": "video/mp4",
            }
            await hass.async_add_executor_job(
                _finalize_recording_upload,
                temporary,
                path,
                media_dir / f".{recording_id}.json",
                metadata,
            )
        except Exception:
            if output is not None:
                await hass.async_add_executor_job(output.close)
            await hass.async_add_executor_job(_remove_file, temporary)
            raise
        coordinator.device.health["recordings"] = {
            "count": len(await hass.async_add_executor_job(_list_recordings, media_dir)),
            "latest_id": recording_id,
            "latest_at": observed_at,
            "latest_camera_id": camera_id,
        }
        coordinator._touch()
        return self.json({"ok": True, "media_id": recording_id, "bytes": written})

    async def get(self, request: web.Request, device_id: str, recording_id: str) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        if device_id not in hass.data.get(DOMAIN, {}).get("coordinators", {}) or not _SAFE_MEDIA_ID.fullmatch(recording_id):
            raise web.HTTPNotFound
        media_dir = _media_directory(hass, device_id)
        path = media_dir / f"{recording_id}.mp4" if media_dir else None
        if path is None or not path.is_file():
            raise web.HTTPNotFound
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="phonesense-{recording_id}.mp4"'})


class PhoneSenseLiveMjpegView(HomeAssistantView):
    """Loopback-only MJPEG source used by Home Assistant's stream worker."""

    requires_auth = False
    url = f"{API_BASE}/devices/{{device_id}}/live/{{camera_id}}"
    name = "api:phonesense:live-mjpeg"

    async def get(self, request: web.Request, device_id: str, camera_id: str) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        remote = request.remote
        token = request.query.get("token", "")
        if (
            coordinator is None
            or remote not in {"127.0.0.1", "::1"}
            or not hmac.compare_digest(token, coordinator.live_stream_token)
        ):
            raise web.HTTPForbidden

        response = web.StreamResponse(
            headers={
                "Content-Type": "multipart/x-mixed-replace;boundary=frameboundary",
                "Cache-Control": "no-store",
            }
        )
        await response.prepare(request)
        last_image: bytes | None = None
        empty_since = time.monotonic()
        try:
            while True:
                image = coordinator.get_live_frame(camera_id)
                if image is None:
                    if time.monotonic() - empty_since > 10:
                        break
                else:
                    empty_since = time.monotonic()
                    if image != last_image:
                        await response.write(
                            b"--frameboundary\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(image)}\r\n\r\n".encode()
                            + image
                            + b"\r\n"
                        )
                        last_image = image
                await asyncio.sleep(0.2)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return response


async def _commands_get(hass: HomeAssistant, device_id: str) -> dict[str, Any] | None:
    coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
    if coordinator is None:
        return None
    return {"commands": await coordinator.async_get_commands()}


async def _register(hass: HomeAssistant, payload: dict[str, Any]) -> web.Response:
    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not _SAFE_DEVICE_ID.fullmatch(device_id):
        return web.json_response({"error": "device_id_required"}, status=HTTPStatus.BAD_REQUEST)
    coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
    if coordinator is None:
        platform = payload.get("platform") if payload.get("platform") in {"android", "ios"} else "phone"
        device_name = payload.get("device_name")
        if not isinstance(device_name, str) or not device_name.strip():
            device_name = default_device_name(platform)
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={CONF_DEVICE_ID: device_id, CONF_DEVICE_NAME: device_name.strip()[:64]},
        )
        await hass.async_block_till_done()
        coordinator = hass.data.get(DOMAIN, {}).get("coordinators", {}).get(device_id)
        if coordinator is None:
            return web.json_response({"error": "device_setup_failed"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
    protocol_error = _protocol_error(payload)
    if protocol_error:
        coordinator.device.health["protocol_error"] = protocol_error
        coordinator._touch()
        return _protocol_failure(protocol_error)
    coordinator.device.health.pop("protocol_error", None)
    # Existing devices use registration as an instance-identity probe before
    # every upload candidate. The immediately following batch/health/commands
    # request records presence, so persisting this probe would only double
    # steady-state writes under high-rate BLE traffic.
    selected = _SUPPORTED_PROTOCOLS[-1]
    return web.json_response({"device_id": device_id, "instance_id": hass.data[DOMAIN]["store"].data["instance_id"], "protocol_version": selected, "protocol": {"selected": selected, "server_supported": list(_SUPPORTED_PROTOCOLS)}, "features": {"statistics_backfill": True, "snapshot_upload_v2": True, "ble_remote_scanner": True, "outbound_live_camera": True, "lan_rtsp": False, "webrtc_signaling": False}})
