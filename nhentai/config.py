import json
import os
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nh-api"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_api_key() -> Optional[str]:
    env_key = os.environ.get("NH_API_KEY")
    if env_key:
        return env_key
    return _load().get("api_key")


def set_api_key(api_key: str) -> None:
    data = _load()
    data["api_key"] = api_key
    _save(data)


def delete_api_key() -> bool:
    data = _load()
    if "api_key" in data:
        del data["api_key"]
        _save(data)
        return True
    return False
