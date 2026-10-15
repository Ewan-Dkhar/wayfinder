"""Persistent configuration manager for Wayfinder.

Handles cross-platform storage for user preferences (such as the active local SLM model)
in standard OS application directories, eliminating the need for environment variables
or terminal interactions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Detect OS standard user configuration directories
if sys.platform == "win32":
    APP_DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "wayfinder"
elif sys.platform == "darwin":
    APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "wayfinder"
else:
    # Linux / FreeDesktop XDG standard
    APP_DATA_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wayfinder"

CONFIG_FILE_PATH = APP_DATA_DIR / "config.json"
FALLBACK_CONFIG_PATH = Path(__file__).resolve().parents[1] / "wayfinder_config.json"

DEFAULT_MODEL = os.getenv("WAYFINDER_MODEL", "llama3.2:3b")
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")

DEFAULT_CONFIG: Dict[str, Any] = {
    "model": DEFAULT_MODEL,
    "ollama_url": DEFAULT_OLLAMA_URL,
    "timeout_seconds": 4.0,
}


def get_config_path() -> Path:
    """Returns the writable config file path, falling back to local workspace if needed."""
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return CONFIG_FILE_PATH
    except Exception:
        return FALLBACK_CONFIG_PATH


def load_config() -> Dict[str, Any]:
    """Loads settings from disk, merged with defaults."""
    config = dict(DEFAULT_CONFIG)
    target_path = get_config_path()

    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    config.update(saved)
        except Exception:
            pass

    return config


def save_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Updates and saves persistent settings to disk."""
    current = load_config()
    current.update(updates)

    target_path = get_config_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception:
        # Fallback to local workspace if standard config dir fails
        try:
            with open(FALLBACK_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
        except Exception:
            pass

    return current


def get_configured_model() -> str:
    """Convenience accessor for the user's active model."""
    config = load_config()
    return str(config.get("model", DEFAULT_MODEL))
