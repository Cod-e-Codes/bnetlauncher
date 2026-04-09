"""
Install checks and repair guidance.

Launches reuse the game's bottle when the .exe lives under drive_c; otherwise
the Blizzard app prefix (or ~/.wine) is used — see WineRunner.resolve_launch_prefix.
Blizzard's Scan and Repair lives inside the official desktop app; this module
surfaces checks and guidance only.
"""
from __future__ import annotations

import os
from pathlib import Path

from bnetlauncher.game_manager import Game
from bnetlauncher import wow_addons
from bnetlauncher.wine_runner import WineRunner


def verify_install(game: Game, wine_runner: WineRunner) -> tuple[bool, list[str]]:
    """Return (ok, issue messages). Checks exe path and prefix layout."""
    issues: list[str] = []
    if not game.installed or not (game.install_path or "").strip():
        issues.append(
            "No install detected. Refresh the library or install the game "
            "via the Blizzard desktop app inside Wine."
        )
        return False, issues

    exe = Path(game.install_path)
    if not exe.is_file():
        issues.append(f"Executable missing: {exe}")
    elif not os.access(exe, os.R_OK):
        issues.append(f"Cannot read executable: {exe}")

    prefix = wine_runner.resolve_launch_prefix(str(exe), game.id)
    drive_c = Path(prefix) / "drive_c"
    if not drive_c.is_dir():
        issues.append(f"Wine prefix has no drive_c: {prefix}")

    if game.id == "wow" and exe.is_file():
        _ok_wow, wow_issues = wow_addons.verify_wow_addon_layout(exe)
        issues.extend(wow_issues)

    return len(issues) == 0, issues


def repair_instructions_text() -> str:
    return (
        "Open the Blizzard desktop app in Wine, use the game's Options menu, and run "
        "Scan and Repair. Then return here and click Refresh. "
        "If Wine misbehaves, try a new prefix or reinstall the game in that prefix."
    )
