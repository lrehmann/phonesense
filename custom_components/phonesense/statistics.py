"""Historical aggregate import helpers for PhoneSense streams."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any


def statistic_id(device_id: str, stream_id: str) -> str:
    """Return a stable Home Assistant statistic id."""
    clean_device = re.sub(r"[^a-z0-9_]", "_", device_id.lower())
    clean_stream = re.sub(r"[^a-z0-9_]", "_", stream_id.lower())
    return f"phonesense:{clean_device}_{clean_stream}"[:255]


def aggregate_import(sample: dict[str, Any], device_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Translate a PhoneSense aggregate sample into HA recorder metadata/data."""
    aggregate = sample.get("aggregate")
    if not isinstance(aggregate, dict) or sample.get("kind") != "measurement":
        return None
    required = ("bucket_start", "bucket_end", "mean", "min", "max", "count")
    if any(key not in aggregate for key in required):
        return None
    try:
        start = datetime.fromisoformat(str(aggregate["bucket_start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(aggregate["bucket_end"]).replace("Z", "+00:00"))
        count = int(aggregate["count"])
        mean = float(aggregate["mean"])
        minimum = float(aggregate["min"])
        maximum = float(aggregate["max"])
    except (TypeError, ValueError):
        return None
    # Home Assistant's external-statistics API accepts hourly rows only. The
    # phones compact one- and five-minute buckets locally, so those samples
    # must still be acknowledged and update the current entity without being
    # passed to an API that would raise and reject the entire telemetry batch.
    if start.minute != 0 or start.second != 0 or start.microsecond != 0 or end - start != timedelta(hours=1):
        return None
    if count <= 0 or minimum > maximum or end <= start:
        return None
    metadata = {
        "mean_type": 1,
        "has_sum": True,
        "name": f"PhoneSense {sample['stream_id']}",
        "source": "phonesense",
        "statistic_id": statistic_id(device_id, sample["stream_id"]),
        "unit_class": None,
        "unit_of_measurement": sample.get("unit"),
    }
    data = {
        "start": start,
        "mean": mean,
        "min": minimum,
        "max": maximum,
        "sum": mean * count,
        "mean_weight": count,
    }
    return metadata, data


def async_import_aggregate(hass: Any, sample: dict[str, Any], device_id: str) -> bool:
    """Queue a supported Home Assistant recorder aggregate import."""
    imported = aggregate_import(sample, device_id)
    if imported is None:
        return False
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    metadata, data = imported
    async_add_external_statistics(hass, metadata, [data])
    return True
