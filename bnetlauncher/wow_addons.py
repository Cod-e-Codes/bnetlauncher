"""
World of Warcraft add-on folders.

Detects `Interface/AddOns` under each product directory (`_retail_`, `_classic_`,
etc.) next to the resolved game executable, creates missing folders, and opens
them in the desktop file manager.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

# Names Blizzard uses under each flavor directory (Linux paths mirror Windows layout).
_WOW_GAME_EXES = frozenset({"Wow.exe", "WowClassic.exe"})

_KNOWN_FLAVOR_LABELS: dict[str, str] = {
    "_retail_": "Retail",
    "_classic_": "Classic",
    "_classic_era_": "Classic Era",
    "_classic_tbc_": "Burning Crusade Classic",
    "_classic_wrath_": "Wrath of the Lich King Classic",
    "_classic_cataclysm_": "Cataclysm Classic",
}


def flavor_label(folder_name: str) -> str:
    """Human-readable label for a WoW product directory (e.g. `_retail_`)."""
    if folder_name in _KNOWN_FLAVOR_LABELS:
        return _KNOWN_FLAVOR_LABELS[folder_name]
    inner = folder_name.strip("_").replace("_", " ").strip()
    return inner.title() if inner else folder_name


def wow_install_root(wow_game_exe: Path) -> Path | None:
    """
    Return the `World of Warcraft` directory given a path to Wow.exe or WowClassic.exe.

    Layout: `<WoW>/<_retail_|_classic_|…>/<Wow.exe|WowClassic.exe>`
    """
    wow_game_exe = wow_game_exe.resolve()
    if not wow_game_exe.is_file():
        return None
    if wow_game_exe.name not in _WOW_GAME_EXES:
        return None
    flavor = wow_game_exe.parent
    root = flavor.parent
    if not root.is_dir():
        return None
    return root


def _flavor_has_game_executable(flavor_dir: Path) -> bool:
    for name in _WOW_GAME_EXES:
        if (flavor_dir / name).is_file():
            return True
    return False


def addons_directory_for_flavor(flavor_dir: Path) -> Path:
    """Return `Interface/AddOns` path for a flavor directory (may not exist yet)."""
    return flavor_dir / "Interface" / "AddOns"


def enumerate_addon_folders(wow_game_exe: Path) -> list[tuple[str, Path]]:
    """
    List `(label, addons_dir)` for each installed WoW product under the same root.

    `addons_dir` is the path to `Interface/AddOns` (created on open if missing).
    """
    root = wow_install_root(wow_game_exe)
    if root is None:
        return []

    pairs: list[tuple[str, Path]] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []

    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("_"):
            continue
        if not _flavor_has_game_executable(child):
            continue
        pairs.append((flavor_label(name), addons_directory_for_flavor(child)))

    pairs.sort(key=lambda x: x[0].lower())
    return pairs


def ensure_addons_directory(addons_dir: Path) -> tuple[bool, str]:
    """Create `Interface/AddOns` if needed. Returns (ok, error message)."""
    try:
        addons_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, str(e)
    return True, ""


def open_directory_in_file_manager(path: Path) -> tuple[bool, str]:
    """Open a directory URI with the default app (file manager on Linux)."""
    path = path.resolve()
    if not path.is_dir():
        return False, f"Not a directory: {path}"
    xdg = which("xdg-open")
    if xdg:
        try:
            subprocess.Popen(
                [xdg, str(path)],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, ""
        except OSError as e:
            return False, str(e)
    return False, "xdg-open not found on PATH"


def ensure_and_open_addons(addons_dir: Path) -> tuple[bool, str]:
    """Ensure `Interface/AddOns` exists, then open it in the file manager."""
    ok, err = ensure_addons_directory(addons_dir)
    if not ok:
        return False, err
    return open_directory_in_file_manager(addons_dir)


def verify_wow_addon_layout(wow_game_exe: Path) -> tuple[bool, list[str]]:
    """
    Return (ok, issues) for WoW add-on paths relative to the detected install.

    Missing `Interface/AddOns` alone is not an error (the launcher creates it on
    open). Reports broken layouts (e.g. Interface is a file).
    """
    issues: list[str] = []
    root = wow_install_root(wow_game_exe)
    if root is None:
        return True, []

    pairs = enumerate_addon_folders(wow_game_exe)
    if not pairs:
        issues.append(
            "WoW install root has no `_retail_` / `_classic_` style folders with "
            "Wow.exe or WowClassic.exe."
        )
        return False, issues

    for label, addons in pairs:
        iface = addons.parent
        if iface.exists() and not iface.is_dir():
            issues.append(f"{label}: Interface path exists but is not a directory: {iface}")

    return len(issues) == 0, issues
