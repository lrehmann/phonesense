from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

VALID_KINDS = {"measurement", "state", "event", "location", "diagnostic", "ble_advertisement", "media_reference"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def command_expiry_rejection(command: dict[str, Any], now: datetime | None = None) -> str | None:
    """Reject stale or malformed commands before they can reach a phone."""
    expires_at = command.get("expires_at")
    if expires_at is None:
        return None
    if not isinstance(expires_at, str) or not expires_at.strip():
        return "invalid_command"
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return "invalid_command"
    if expiry.tzinfo is None:
        return "invalid_command"
    return "expired" if expiry <= (now or datetime.now(timezone.utc)) else None


def stream_key(sample: dict[str, Any]) -> tuple[str, str, str]:
    return (sample["device_id"], sample["boot_id"], sample["stream_id"])


def sample_identity(sample: dict[str, Any]) -> tuple[str, str, str, int]:
    return (*stream_key(sample), sample["sequence"])


def validate_sample(sample: dict[str, Any], device_id: str | None = None) -> str | None:
    required = ("schema_version", "device_id", "boot_id", "stream_id", "sequence", "observed_at", "kind")
    missing = [key for key in required if key not in sample]
    if missing:
        return f"missing:{','.join(missing)}"
    if sample["schema_version"] != 1:
        return "unsupported_schema_version"
    if device_id is not None and sample["device_id"] != device_id:
        return "device_mismatch"
    if not isinstance(sample["sequence"], int) or sample["sequence"] < 0:
        return "invalid_sequence"
    if sample["kind"] not in VALID_KINDS:
        return "invalid_kind"
    if not isinstance(sample["observed_at"], str):
        return "invalid_observed_at"
    if "aggregate" in sample:
        aggregate = sample["aggregate"]
        required_aggregate = ("bucket_start", "bucket_end", "count", "min", "max", "mean")
        if sample["kind"] != "measurement" or not isinstance(aggregate, dict) or any(key not in aggregate for key in required_aggregate):
            return "invalid_aggregate"
        if not isinstance(aggregate["count"], int) or aggregate["count"] < 1:
            return "invalid_aggregate"
        sequence_start = aggregate.get("sequence_start")
        sequence_end = aggregate.get("sequence_end")
        if (sequence_start is None) != (sequence_end is None):
            return "invalid_aggregate"
        if sequence_start is not None and (
            not isinstance(sequence_start, int)
            or not isinstance(sequence_end, int)
            or sequence_start < 0
            or sequence_end < sequence_start
            or sample["sequence"] != sequence_start
        ):
            return "invalid_aggregate"
    return None


def ack_response(batch_id: str, accepted: dict[tuple[str, str], int], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "accepted": [
            {"boot_id": boot_id, "stream_id": stream_id, "acked_through": sequence}
            for (boot_id, stream_id), sequence in sorted(accepted.items())
        ],
        "rejected": rejected,
        "server_time": utc_now(),
        "next_config_version": None,
        "pending_commands": 0,
    }


def contiguous_ack(sequences: list[int], current: int = -1) -> int:
    expected = current + 1
    present = set(sequences)
    while expected in present:
        expected += 1
    return expected - 1


def contiguous_ack_ranges(ranges: list[tuple[int, int]], current: int = -1) -> int:
    next_sequence = current + 1
    for start, end in sorted(ranges):
        if end < next_sequence:
            continue
        if start > next_sequence:
            break
        next_sequence = max(next_sequence, end + 1)
    return next_sequence - 1
