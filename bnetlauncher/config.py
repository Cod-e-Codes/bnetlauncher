"""
Configuration management. Stores settings in ~/.config/bnetlauncher/config.json.
"""
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _debug_enabled() -> bool:
    v = (os.environ.get("BNETLAUNCHER_DEBUG") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _debug_log(msg: str, exc: BaseException | None = None) -> None:
    if not _debug_enabled():
        return
    print(f"[bnetlauncher:debug] {msg}", file=sys.stderr, flush=True)
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bnetlauncher"
_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "bnetlauncher"
_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bnetlauncher"

CONFIG_FILE = _CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    # Authentication
    "bnet_client_id": "",
    "bnet_client_secret": "",
    "bnet_region": "us",
    "access_token": "",
    "token_expiry": 0,

    # Wine / Proton
    "wine_executable": "wine",          # path to wine binary or 'wine'
    "proton_path": "",                  # path to Proton installation directory
    "use_proton": False,                # prefer Proton over system Wine
    "wine_prefix_dir": str(_DATA_DIR / "prefixes"),
    "dxvk_enabled": True,
    "esync_enabled": True,
    "fsync_enabled": True,

    # Display (Wayland/resize safety)
    "force_borderless": True,           # use borderless windowed to avoid resize crashes
    "fake_fullscreen": True,            # WINE_FULLSCREEN_FAKE_FULLSCREEN
    "fsr_enabled": False,               # AMD FSR upscaling via Wine
    "virtual_desktop": False,           # run inside Wine virtual desktop
    "virtual_desktop_res": "1920x1080",

    # Game library
    "games_dir": str(_DATA_DIR / "games"),
    "custom_game_paths": [],            # list of extra scan directories
    "show_unsupported_games": False,   # show catalogue titles marked not viable on Linux/Wine

    # UI
    "window_width": 1280,
    "window_height": 800,
    "window_maximized": False,
    "sidebar_visible": True,
    "theme": "dark",                    # 'dark' | 'light' | 'system'
}


class Config:
    """Thread-safe config wrapper with dot-access and auto-save."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {**DEFAULTS}
        self._load()
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Path(self.get("wine_prefix_dir")).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open() as f:
                    saved = json.load(f)
                self._data.update(saved)
            except (json.JSONDecodeError, OSError) as e:
                _debug_log(f"config load failed ({CONFIG_FILE})", e)

    def save(self) -> None:
        try:
            with CONFIG_FILE.open("w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            _debug_log(f"config save failed ({CONFIG_FILE})", e)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key: str, value: Any, *, autosave: bool = True) -> None:
        self._data[key] = value
        if autosave:
            self.save()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    @property
    def cache_dir(self) -> Path:
        return _CACHE_DIR

    @property
    def data_dir(self) -> Path:
        return _DATA_DIR

    @property
    def config_dir(self) -> Path:
        return _CONFIG_DIR


# Module-level singleton
_instance: Config | None = None


def get_config() -> Config:
    global _instance
    if _instance is None:
        _instance = Config()
    return _instance
