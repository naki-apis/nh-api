import json
import os

_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".nh-api", "settings.json")
_VALID_FORMATS = ("cbz", "pdf", "raw", "zip")


def _load_settings():
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(data):
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_default_format():
    fmt = _load_settings().get("default_format")
    return fmt if fmt in _VALID_FORMATS else "cbz"


def set_default_format(fmt):
    if fmt not in _VALID_FORMATS:
        raise ValueError("Invalid format: {}".format(fmt))
    data = _load_settings()
    data["default_format"] = fmt
    _save_settings(data)
