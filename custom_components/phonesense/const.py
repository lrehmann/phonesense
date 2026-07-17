DOMAIN = "phonesense"
NAME = "PhoneSense"
VERSION = "1.0"
SCHEMA_VERSION = 1
STORAGE_VERSION = 1
STORAGE_KEY = "phonesense"
INSTANCE_ID_KEY = "instance_id"
API_BASE = "/api/phonesense/v1"

PLATFORMS = ["sensor", "binary_sensor", "device_tracker", "camera", "button", "switch", "select", "number", "light", "media_player"]

CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"

ATTR_OBSERVED_AT = "observed_at"
ATTR_RECEIVED_AT = "received_at"
ATTR_QUALITY = "quality"
ATTR_CAPABILITY = "capability"


def default_device_name(platform: str) -> str:
    """Return a correctly styled generated product/device name."""
    labels = {"android": "Android", "ios": "iOS"}
    return f"PhoneSense {labels.get(platform, 'phone')}"


def normalize_device_name(name: str, platform: str) -> str:
    """Repair a legacy generated name without changing user-selected names."""
    if name == "PhoneSense Ios" and platform == "ios":
        return default_device_name(platform)
    return name
