from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import secrets
import time
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .models import Capability, Command, PhoneSenseDevice, StreamState
from .protocol import ack_response, command_expiry_rejection, contiguous_ack_ranges, validate_sample
from .storage import PhoneSenseStore
from .statistics import async_import_aggregate
from .repairs import update_device_issues


class PhoneSenseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Push coordinator with a local freshness tick.

    Phone traffic still arrives exclusively through push endpoints. The
    lightweight timer only asks entities to recompute staleness so an offline
    phone transitions from a restored value or ``unknown`` to ``unavailable``
    without waiting forever for another push that cannot arrive.
    """

    def __init__(self, hass: HomeAssistant, store: PhoneSenseStore, device: PhoneSenseDevice) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(DOMAIN),
            name=f"PhoneSense {device.name}",
            update_interval=timedelta(seconds=60),
        )
        self.store = store
        self.device = device
        # Live camera frames are intentionally transient. Persisting them would
        # write several images per second into Home Assistant's storage file.
        self.live_frames: dict[str, dict[str, Any]] = {}
        self._last_live_presence_monotonic = 0.0
        self.live_stream_token = secrets.token_urlsafe(32)
        self.device.health.setdefault("effective_configuration", self._default_configuration())
        self._mirror_configuration(self.device.health["effective_configuration"])
        self.data = self._as_data()

    async def _async_update_data(self) -> dict[str, Any]:
        """Notify entities to recompute freshness without contacting the phone."""
        update_device_issues(self.hass, self.device)
        return self._as_data()

    def set_live_frame(
        self,
        camera_id: str,
        image: bytes,
        sequence: int,
        observed_at: str | None,
    ) -> bool:
        """Keep the newest outbound camera frame in memory only."""
        previous = self.live_frames.get(camera_id)
        if previous is not None and sequence <= int(previous.get("sequence", -1)):
            # Publisher counters are process-local. Preserve ordering while a
            # stream is active, but accept a reset after the prior stream has
            # visibly gone stale (for example after an app update/relaunch).
            age = time.monotonic() - float(previous.get("received_monotonic", 0.0))
            if age <= 5.0:
                return False
        self.live_frames[camera_id] = {
            "image": image,
            "sequence": sequence,
            "observed_at": observed_at,
            "received_monotonic": time.monotonic(),
        }
        self._reflect_live_camera_session(camera_id)
        return True

    def _reflect_live_camera_session(self, camera_id: str) -> None:
        """Make frame-proven camera state visible without waiting for health polling."""
        device = getattr(self, "device", None)
        if device is None:
            return
        sessions = device.health.setdefault("media_sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            device.health["media_sessions"] = sessions
        changed = False
        if str(device.platform).lower() == "ios":
            for active_camera_id in list(sessions):
                if active_camera_id.startswith("camera.") and active_camera_id != camera_id:
                    sessions.pop(active_camera_id, None)
                    # iOS exposes one AVFoundation capture session. Once a
                    # frame proves that another lens has taken ownership, its
                    # predecessor can no longer be live. Remove the old frame
                    # now so Home Assistant does not display the inactive
                    # camera as streaming until the generic five-second cache
                    # window expires.
                    self.live_frames.pop(active_camera_id, None)
                    changed = True
        existing = sessions.get(camera_id)
        if not isinstance(existing, dict) or existing.get("active") is not True:
            sessions[camera_id] = {
                "camera_id": camera_id,
                "active": True,
                "source": "live_frame",
            }
            changed = True
        if changed:
            self.data = self._as_data()
            self.async_set_updated_data(self.data)

    def mark_live_presence(self, minimum_interval_seconds: float = 30.0) -> bool:
        """Treat an authenticated frame as presence without persisting every frame."""
        now = time.monotonic()
        if now - self._last_live_presence_monotonic < minimum_interval_seconds:
            return False
        self._last_live_presence_monotonic = now
        self.device.last_seen = datetime.now(timezone.utc)
        self.data = self._as_data()
        self.async_set_updated_data(self.data)
        return True

    def get_live_frame(self, camera_id: str, max_age_seconds: float = 5.0) -> bytes | None:
        """Return a recent JPEG without touching the persistent coordinator."""
        frame = self.live_frames.get(camera_id)
        if frame is None or time.monotonic() - float(frame["received_monotonic"]) > max_age_seconds:
            return None
        return frame["image"]

    @staticmethod
    def _default_configuration() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "config_version": 0,
            "profile": "stationary_sensor",
            "modules": {
                "motion": {"enabled": True, "sample_rate_hz": 25, "publish_interval_ms": 5000, "impact_threshold_m_s2": 20},
                "location": {"enabled": False},
                "network": {"enabled": True, "include_local_addresses": False},
                "ble_proxy": {"enabled": False, "batch_interval_ms": 1000, "duplicate_window_ms": 250},
                "camera": {"enabled": False},
                "audio": {"enabled": False},
            },
            "sync": {"wifi_only_media": True, "allow_metered_telemetry": True, "max_batch_bytes": 262144},
            "retention": {"telemetry_days": 7, "telemetry_bytes": 262_144_000, "media_bytes": 262_144_000},
        }

    def _prepare_configuration(self, requested: dict[str, Any]) -> dict[str, Any]:
        current = self.device.health.get("effective_configuration") or self._default_configuration()
        if "config_version" in requested:
            try:
                if int(requested["config_version"]) <= int(current.get("config_version", 0)):
                    return self._deep_merge(current, {})
            except (TypeError, ValueError):
                return self._deep_merge(current, {})
        effective = self._deep_merge(current, requested)
        effective["schema_version"] = 1
        effective["config_version"] = max(int(effective.get("config_version", 0)), int(current.get("config_version", 0)) + (0 if "config_version" in requested else 1))
        if effective.get("profile") not in {"stationary_sensor", "camera_monitor", "mobile_tracker", "bluetooth_proxy", "low_power", "custom"}:
            effective["profile"] = current.get("profile", "stationary_sensor")
        modules = effective.setdefault("modules", {})
        for name in list(modules):
            if name not in {"motion", "location", "network", "ble_proxy", "camera", "audio"}:
                modules.pop(name, None)
        self._clamp(modules.get("motion"), "sample_rate_hz", 1, 100)
        self._clamp(modules.get("motion"), "publish_interval_ms", 1000, 3_600_000)
        self._clamp(modules.get("motion"), "impact_threshold_m_s2", 1, 100)
        self._clamp(modules.get("ble_proxy"), "batch_interval_ms", 250, 60_000)
        self._clamp(modules.get("ble_proxy"), "duplicate_window_ms", 0, 60_000)
        self._clamp(effective.setdefault("sync", {}), "max_batch_bytes", 16_384, 1_048_576)
        self._clamp(effective.setdefault("retention", {}), "telemetry_days", 1, 30)
        self._clamp(effective["retention"], "telemetry_bytes", 1_048_576, 524_288_000)
        self._clamp(effective["retention"], "media_bytes", 1_048_576, 524_288_000)
        return effective

    @staticmethod
    def _deep_merge(base: dict[str, Any], requested: dict[str, Any]) -> dict[str, Any]:
        result = {key: (value.copy() if isinstance(value, dict) else value) for key, value in base.items()}
        for key, value in requested.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = PhoneSenseCoordinator._deep_merge(result[key], value)
            elif key in result:
                result[key] = value
        return result

    @staticmethod
    def _clamp(values: dict[str, Any] | None, key: str, minimum: int, maximum: int) -> None:
        if values is None or key not in values:
            return
        try:
            values[key] = max(minimum, min(maximum, int(values[key])))
        except (TypeError, ValueError):
            values.pop(key, None)

    def _mirror_configuration(self, config: dict[str, Any]) -> None:
        self.device.health["effective_configuration"] = config
        self.device.health["profile"] = config.get("profile", "stationary_sensor")
        self.device.health["requested_modules"] = {key: bool(value.get("enabled", False)) for key, value in config.get("modules", {}).items() if isinstance(value, dict)}
        self.device.health["intervals"] = {
            "location_interval": config.get("modules", {}).get("location", {}).get("interval_ms", 5000) / 1000,
            "motion_publish_interval": config.get("modules", {}).get("motion", {}).get("publish_interval_ms", 5000) / 1000,
        }

    def _as_data(self) -> dict[str, Any]:
        return {
            "device_id": self.device.device_id,
            "name": self.device.name,
            "platform": self.device.platform,
            "last_seen": self.device.last_seen.isoformat() if self.device.last_seen else None,
            "capabilities": self.device.capabilities,
            "streams": self.device.streams,
            "health": self.device.health,
            "commands": self.device.commands,
        }

    def _touch(self) -> None:
        self.device.last_seen = datetime.now(timezone.utc)
        self._persist()
        self.data = self._as_data()
        self.async_set_updated_data(self.data)
        update_device_issues(self.hass, self.device)

    async def async_set_capabilities(self, payload: dict[str, Any]) -> None:
        self.device.platform = payload.get("platform", self.device.platform)
        self.device.os_version = payload.get("os_version", self.device.os_version)
        self.device.app_version = payload.get("app_version", self.device.app_version)
        self.device.capabilities = {
            item["id"]: Capability(item["id"], item["status"], item.get("metadata", {}))
            for item in payload.get("capabilities", [])
            if isinstance(item, dict) and item.get("id") and item.get("status")
        }
        self._persist()
        self._touch()

    async def async_queue_command(
        self,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        requires_local_arming: bool = False,
        ttl_seconds: int = 300,
    ) -> Command:
        if command_type == "apply_configuration":
            payload = self._prepare_configuration(payload or {})
            self._mirror_configuration(payload)
        now = datetime.now(timezone.utc)
        command = Command(
            command_id=str(uuid4()),
            type=command_type,
            payload=payload or {},
            issued_at=now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            requires_local_arming=requires_local_arming,
        )
        self.device.commands[command.command_id] = command
        self._persist()
        self._touch()
        self.hass.bus.async_fire("phonesense_command", {
            "device_id": self.device.device_id,
            "command_id": command.command_id,
            "command": {
                "type": command.type,
                "issued_at": command.issued_at,
                "expires_at": command.expires_at,
                "requires_local_arming": command.requires_local_arming,
                "payload": command.payload,
            },
        })
        return command

    async def async_get_commands(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        changed = False
        for command in self.device.commands.values():
            if command.state in {"succeeded", "failed", "rejected", "expired"}:
                continue
            expiry_rejection = command_expiry_rejection({"expires_at": command.expires_at}, now)
            if expiry_rejection:
                command.state = "expired" if expiry_rejection == "expired" else "rejected"
                command.result = {"status": "rejected", "code": expiry_rejection}
                changed = True
                continue
            if command.state == "pending":
                command.state = "delivered"
                changed = True
            active.append({
                "command_id": command.command_id,
                "type": command.type,
                "issued_at": command.issued_at,
                "expires_at": command.expires_at,
                "requires_local_arming": command.requires_local_arming,
                "payload": command.payload,
            })
        if changed:
            self._persist()
        return active

    async def async_set_command_result(self, command_id: str, result: dict[str, Any]) -> bool:
        command = self.device.commands.get(command_id)
        if command is None:
            return False
        command.result = result
        if isinstance(result.get("effective"), dict):
            self._mirror_configuration(result["effective"])
        status = result.get("status", "succeeded")
        command.state = status if status in {"succeeded", "failed", "rejected"} else "succeeded"
        self._persist()
        self._touch()
        return True

    async def async_ingest_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        accepted_candidates: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        rejected: list[dict[str, Any]] = []
        self._apply_queue_floors(payload)
        for sample in payload.get("samples", []):
            error = validate_sample(sample, self.device.device_id)
            if error:
                rejected.append({"boot_id": sample.get("boot_id", ""), "stream_id": sample.get("stream_id", ""), "sequence": sample.get("sequence", -1), "code": error})
                continue
            identity = (sample["boot_id"], sample["stream_id"], sample["sequence"])
            watermark = self._watermark((sample["boot_id"], sample["stream_id"]))
            aggregate = sample.get("aggregate") if isinstance(sample.get("aggregate"), dict) else {}
            sequence_end = aggregate.get("sequence_end", sample["sequence"])
            # Current-state rows are deliberately coalesced on the phone: a
            # newer value supersedes older pending values from the same
            # stream. Cover that deleted range when acknowledging the newer
            # state. Measurements, events, and other durable sample kinds
            # retain strict gap-aware acknowledgement.
            sequence_start = sample["sequence"]
            if sample.get("kind") == "state" and sample["sequence"] > watermark:
                sequence_start = watermark + 1
            if identity in self.device.seen_keys or sample["sequence"] <= watermark:
                accepted_candidates[(sample["boot_id"], sample["stream_id"])].append((sequence_start, sequence_end))
                continue
            self._remember_identity(identity)
            if sample.get("kind") == "ble_advertisement":
                scanner_state = self.hass.data.get(DOMAIN, {}).get("scanners", {}).get(self.device.device_id)
                value = sample.get("value")
                if scanner_state and isinstance(value, dict):
                    scanner_state[0].async_on_advertisement(value)
            if sample.get("kind") == "event":
                # Keep event samples in the durable stream and also expose a
                # transient HA event for automations.  The stream remains the
                # source of truth when Home Assistant was offline.
                self.hass.bus.async_fire("phonesense_event", {
                    "device_id": self.device.device_id,
                    "stream_id": sample["stream_id"],
                    "sequence": sample["sequence"],
                    "observed_at": sample["observed_at"],
                    "value": sample.get("value"),
                    "unit": sample.get("unit"),
                    "quality": sample.get("quality", {}),
                })
            if sample.get("aggregate"):
                async_import_aggregate(self.hass, sample, self.device.device_id)
            accepted_candidates[(sample["boot_id"], sample["stream_id"])].append((sequence_start, sequence_end))
            state = self.device.streams.get(sample["stream_id"]) or StreamState(sample["stream_id"])
            if state.observed_at is None or sample["observed_at"] >= state.observed_at:
                state.value = sample.get("value")
                state.unit = sample.get("unit")
                state.kind = sample["kind"]
                state.observed_at = sample["observed_at"]
                state.quality = sample.get("quality", {})
            state.last_sequence = max(state.last_sequence, sample["sequence"])
            self.device.streams[state.stream_id] = state
        accepted = {}
        for key, ranges in accepted_candidates.items():
            watermark = self._watermark(key)
            # A phone can collect samples before the Bridge integration is
            # installed (Core mode), so its first Bridge sequence need not be
            # zero. Establish the stream exactly once at the first observed
            # range, while still stopping at any gap inside this batch.
            if watermark == -1 and ranges:
                watermark = min(start for start, _end in ranges) - 1
            accepted[key] = contiguous_ack_ranges(ranges, watermark)
        for key, value in accepted.items():
            self._set_watermark(key, value)
        self._touch()
        # The phone deletes rows as soon as this response acknowledges them.
        # Do not let an acknowledgement escape before its watermark is on
        # disk: a Home Assistant restart in that window would permanently
        # recreate an apparent gap that the phone can no longer replay.
        save = getattr(self.store, "async_save", None)
        if save is not None:
            await save()
        response = ack_response(payload.get("batch_id", ""), accepted, rejected)
        response["commands"] = await self.async_get_commands()
        response["pending_commands"] = len(response["commands"])
        return response

    def _apply_queue_floors(self, payload: dict[str, Any]) -> None:
        """Recover only gaps the authenticated phone proves it no longer retains."""
        samples = payload.get("samples", [])
        if not isinstance(samples, list):
            return
        valid_first_sequences: dict[tuple[str, str], int] = {}
        for sample in samples:
            if not isinstance(sample, dict) or validate_sample(sample, self.device.device_id):
                continue
            key = (sample["boot_id"], sample["stream_id"])
            valid_first_sequences[key] = min(valid_first_sequences.get(key, sample["sequence"]), sample["sequence"])

        recoveries: list[dict[str, Any]] = []
        total_skipped = 0
        floors = payload.get("queue_floors", [])
        if not isinstance(floors, list):
            return
        for floor in floors[:10_000]:
            if not isinstance(floor, dict):
                continue
            boot_id = floor.get("boot_id")
            stream_id = floor.get("stream_id")
            first_sequence = floor.get("first_sequence")
            if (
                not isinstance(boot_id, str)
                or not boot_id
                or not isinstance(stream_id, str)
                or not stream_id
                or not isinstance(first_sequence, int)
                or first_sequence < 0
            ):
                continue
            key = (boot_id, stream_id)
            if valid_first_sequences.get(key) != first_sequence:
                continue
            watermark = self._watermark(key)
            # The normal first-Bridge baseline already handles watermark -1.
            # Floors repair only an established stream with an unreplayable gap.
            if watermark < 0 or first_sequence <= watermark + 1:
                continue
            skipped = first_sequence - watermark - 1
            self._set_watermark(key, first_sequence - 1)
            total_skipped += skipped
            recoveries.append({
                "boot_id": boot_id,
                "stream_id": stream_id,
                "from_sequence": watermark + 1,
                "through_sequence": first_sequence - 1,
                "count": skipped,
            })
        if recoveries:
            audit = self.device.health.setdefault("queue_floor_recovery", {})
            audit["recovered_missing_sequences"] = int(audit.get("recovered_missing_sequences", 0)) + total_skipped
            audit["last_recoveries"] = recoveries[-20:]
            audit["last_recovered_at"] = datetime.now(timezone.utc).isoformat()

    def _watermark(self, key: tuple[str, str]) -> int:
        return int(self.store.data.setdefault("devices", {}).setdefault(self.device.device_id, {}).setdefault("watermarks", {}).get("/".join(key), -1))

    def _remember_identity(self, identity: tuple[str, str, int]) -> None:
        if identity in self.device.seen_keys:
            return
        self.device.seen_keys.add(identity)
        self.device.seen_order.append(identity)
        # Keep restart-safe deduplication bounded. Once a sequence is covered
        # by a contiguous watermark, it no longer needs an explicit ledger row.
        while len(self.device.seen_order) > 8192:
            removed = self.device.seen_order.pop(0)
            self.device.seen_keys.discard(removed)

    def _set_watermark(self, key: tuple[str, str], value: int) -> None:
        self.store.data.setdefault("devices", {}).setdefault(self.device.device_id, {}).setdefault("watermarks", {})["/".join(key)] = value

    async def async_set_health(self, payload: dict[str, Any]) -> None:
        previous_configuration = self.device.health.get("effective_configuration")
        previous_requested_capabilities = self.device.health.get("requested_capabilities")
        self.device.health = payload
        if isinstance(payload.get("effective_configuration"), dict):
            self._mirror_configuration(payload["effective_configuration"])
        elif isinstance(previous_configuration, dict):
            self.device.health["effective_configuration"] = previous_configuration
            self._mirror_configuration(previous_configuration)
        if (
            "requested_capabilities" not in payload
            and isinstance(previous_requested_capabilities, dict)
        ):
            # Older app versions do not include this field. Keep optimistic
            # switch state through rolling upgrades instead of snapping every
            # per-sensor control back to its metadata default.
            self.device.health["requested_capabilities"] = previous_requested_capabilities
        queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else {}
        observed_at = payload.get("last_sync_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if "pending" in queue:
            self.device.streams["network.queue_depth"] = StreamState("network.queue_depth", queue.get("pending", 0), "samples", "diagnostic", observed_at, None, {"dropped": queue.get("dropped", 0), "compacted": queue.get("compacted", 0)}, self.device.streams.get("network.queue_depth", StreamState("network.queue_depth")).last_sequence)
        self._persist()
        self._touch()

    def _persist(self) -> None:
        record = self.store.data.setdefault("devices", {}).setdefault(self.device.device_id, {})
        record.update({
            "name": self.device.name,
            "platform": self.device.platform,
            "os_version": self.device.os_version,
            "app_version": self.device.app_version,
            "capabilities": {key: {"status": value.status, "metadata": value.metadata} for key, value in self.device.capabilities.items()},
            "streams": {key: {"value": value.value, "unit": value.unit, "kind": value.kind, "observed_at": value.observed_at, "quality": value.quality, "last_sequence": value.last_sequence} for key, value in self.device.streams.items()},
            "health": self.device.health,
            "dedup_keys": [list(identity) for identity in self.device.seen_order],
            "commands": {
                key: {
                    "type": value.type,
                    "payload": value.payload,
                    "issued_at": value.issued_at,
                    "expires_at": value.expires_at,
                    "requires_local_arming": value.requires_local_arming,
                    "state": value.state,
                    "result": value.result,
                }
                for key, value in self.device.commands.items()
            },
            "last_seen": self.device.last_seen.isoformat() if self.device.last_seen else None,
        })
        self.hass.async_create_task(self.store.async_save())
