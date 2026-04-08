"""
Game library manager.

Detects Battle.net games installed on the system by scanning registry paths
inside Wine prefixes and known installation directories.  Falls back to user-
configured custom paths.

Game metadata is sourced from a local JSON catalogue (bundled) plus
optional live data from the Blizzard Game Data API when credentials exist.
"""
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

from bnetlauncher.config import get_config


# Known Battle.net game identifiers and their display metadata.
# Executable paths are relative to the default installation root.
CATALOGUE: dict[str, dict] = {
    "wow": {
        "name": "World of Warcraft",
        "slug": "wow",
        "download_product": "wow",
        "install_dir": "World of Warcraft",
        "executables": ["_retail_/Wow.exe", "_classic_/WowClassic.exe"],
        "icon": "wow",
        "description": "The legendary MMORPG.",
        "genre": "MMORPG",
        "background_color": "#1a3a5c",
    },
    "d4": {
        "name": "Diablo IV",
        "slug": "d4",
        "download_product": "diablo4",
        "install_dir": "Diablo IV",
        "executables": ["Diablo IV.exe"],
        "icon": "d4",
        "description": "The ultimate action RPG.",
        "genre": "Action RPG",
        "background_color": "#2a0a0a",
    },
    "ow2": {
        "name": "Overwatch 2",
        "slug": "ow2",
        "download_product": "overwatch",
        "install_dir": "Overwatch",
        "executables": ["Overwatch.exe"],
        "icon": "ow2",
        "description": "Team-based action shooter.",
        "genre": "Hero Shooter",
        "background_color": "#002b5e",
    },
    "hs": {
        "name": "Hearthstone",
        "slug": "hs",
        "download_product": "hearthstone",
        "install_dir": "Hearthstone",
        "executables": ["Hearthstone.exe"],
        "icon": "hs",
        "description": "Strategic card game.",
        "genre": "Card Game",
        "background_color": "#3d1a00",
    },
    "s2": {
        "name": "StarCraft II",
        "slug": "s2",
        "download_product": "starcraft2",
        "install_dir": "StarCraft II",
        "executables": ["SC2.exe", "SC2_x64.exe"],
        "icon": "s2",
        "description": "Premier real-time strategy.",
        "genre": "RTS",
        "background_color": "#0a1a2a",
    },
    "hero": {
        "name": "Heroes of the Storm",
        "slug": "hero",
        "download_product": "heroes",
        "install_dir": "Heroes of the Storm",
        "executables": ["HeroesOfTheStorm.exe", "HeroesOfTheStorm_x64.exe"],
        "icon": "hero",
        "description": "Blizzard universe MOBA.",
        "genre": "MOBA",
        "background_color": "#1a0a2a",
    },
    "d3": {
        "name": "Diablo III",
        "slug": "d3",
        "download_product": "diablo3",
        "install_dir": "Diablo III",
        "executables": ["Diablo III.exe", "Diablo III64.exe"],
        "icon": "d3",
        "description": "Hack-and-slash dungeon crawler.",
        "genre": "Action RPG",
        "background_color": "#1a0505",
    },
    "sc1": {
        "name": "StarCraft Remastered",
        "slug": "sc1",
        "download_product": "scr",
        "install_dir": "StarCraft",
        "executables": ["StarCraft.exe"],
        "icon": "sc1",
        "description": "The original real-time classic, remastered.",
        "genre": "RTS",
        "background_color": "#050f1a",
    },
    "w3": {
        "name": "Warcraft III: Reforged",
        "slug": "w3",
        "download_product": "w3",
        "install_dir": "Warcraft III",
        "executables": ["Warcraft III.exe", "x86_64/Warcraft III.exe"],
        "icon": "w3",
        "description": "Legendary RTS, rebuilt.",
        "genre": "RTS",
        "background_color": "#1a1005",
    },
    "cod": {
        "name": "Call of Duty",
        "slug": "cod",
        "download_product": "cod",
        "install_dir": "Call of Duty",
        "executables": ["cod.exe", "ModernWarfare.exe"],
        "icon": "cod",
        "description": "Premier first-person shooter franchise.",
        "genre": "FPS",
        "background_color": "#0a0a0a",
    },
}


@dataclass
class Game:
    id: str
    name: str
    slug: str
    install_path: str          # absolute path to the exe or '' if not installed
    installed: bool
    genre: str
    description: str
    background_color: str
    icon: str
    size_bytes: int = 0
    last_played: int = 0       # unix timestamp


class GameManager:
    def __init__(self) -> None:
        self.cfg = get_config()
        self._db_path = self.cfg.data_dir / "games.db"
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._init_db()
        self._games: dict[str, Game] = {}
        self._scan()

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                name TEXT,
                slug TEXT,
                install_path TEXT,
                installed INTEGER,
                genre TEXT,
                description TEXT,
                background_color TEXT,
                icon TEXT,
                size_bytes INTEGER DEFAULT 0,
                last_played INTEGER DEFAULT 0
            )
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan(self) -> None:
        """Populate game list from catalogue + disk detection."""
        conn = self._get_conn()

        search_roots = self._collect_search_paths()

        for game_id, meta in CATALOGUE.items():
            install_path = self._find_executable(game_id, meta, search_roots)
            installed = bool(install_path)

            game = Game(
                id=game_id,
                name=meta["name"],
                slug=meta["slug"],
                install_path=install_path,
                installed=installed,
                genre=meta["genre"],
                description=meta["description"],
                background_color=meta["background_color"],
                icon=meta["icon"],
            )

            # Merge with DB for last_played etc.
            row = conn.execute(
                "SELECT * FROM games WHERE id=?", (game_id,)
            ).fetchone()
            if row:
                game.last_played = row["last_played"]
                game.size_bytes = row["size_bytes"]
                # Update install state in DB
                conn.execute(
                    "UPDATE games SET install_path=?, installed=? WHERE id=?",
                    (game.install_path, int(game.installed), game_id),
                )
            else:
                conn.execute("""
                    INSERT INTO games
                    (id, name, slug, install_path, installed, genre,
                     description, background_color, icon, size_bytes, last_played)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    game.id, game.name, game.slug, game.install_path,
                    int(game.installed), game.genre, game.description,
                    game.background_color, game.icon, 0, 0,
                ))

            with self._lock:
                self._games[game_id] = game

        conn.commit()

    def _collect_search_paths(self) -> list[Path]:
        """Return directories to search for game installations."""
        paths: list[Path] = []

        # Configured games directory
        games_dir = self.cfg.get("games_dir")
        if games_dir:
            paths.append(Path(games_dir))

        # Default Windows installation paths via Wine prefixes
        prefix_dir = Path(self.cfg.get("wine_prefix_dir"))
        if prefix_dir.is_dir():
            for prefix in prefix_dir.iterdir():
                drive_c = prefix / "drive_c"
                if drive_c.is_dir():
                    for prog in ["Program Files (x86)/Battle.net",
                                 "Program Files/Battle.net",
                                 "Program Files (x86)",
                                 "Program Files"]:
                        candidate = drive_c / prog
                        if candidate.is_dir():
                            paths.append(candidate)

        # User-configured extra paths
        for p in self.cfg.get("custom_game_paths", []):
            paths.append(Path(p))

        # Steam Battle.net installs (via Proton prefix)
        steam_compat = Path.home() / ".steam/steam/steamapps/compatdata"
        if steam_compat.is_dir():
            for compat in steam_compat.iterdir():
                pfx = compat / "pfx/drive_c/Program Files (x86)"
                if pfx.is_dir():
                    paths.append(pfx)

        return paths

    def _find_executable(
        self,
        game_id: str,
        meta: dict,
        roots: list[Path],
    ) -> str:
        """Return the absolute path to the first found executable, or ''."""
        for root in roots:
            install_dir = root / meta["install_dir"]
            if not install_dir.is_dir():
                # Also check directly under root
                install_dir = root
            for rel_exe in meta["executables"]:
                candidate = install_dir / rel_exe
                if candidate.exists():
                    return str(candidate)
        return ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_all(self) -> list[Game]:
        with self._lock:
            return sorted(
                self._games.values(),
                key=lambda g: (-g.installed, -g.last_played, g.name),
            )

    def install_download_url(self, game_id: str) -> str:
        """Blizzard download page for a catalogue game; page usually offers Battle.net-Setup.exe."""
        meta = CATALOGUE.get(game_id)
        if not meta:
            return "https://download.battle.net/en-us/"
        product = meta.get("download_product", "")
        if product:
            return f"https://download.battle.net/en-us/?product={product}"
        return "https://download.battle.net/en-us/"

    def get(self, game_id: str) -> Optional[Game]:
        with self._lock:
            return self._games.get(game_id)

    def update_last_played(self, game_id: str) -> None:
        import time
        ts = int(time.time())
        with self._lock:
            if game_id in self._games:
                self._games[game_id].last_played = ts
        conn = self._get_conn()
        conn.execute(
            "UPDATE games SET last_played=? WHERE id=?", (ts, game_id)
        )
        conn.commit()

    def add_custom_game(self, exe_path: str, name: str) -> Game:
        """Register a custom / non-catalogue game."""
        import hashlib
        game_id = "custom_" + hashlib.md5(exe_path.encode()).hexdigest()[:8]
        game = Game(
            id=game_id,
            name=name,
            slug=game_id,
            install_path=exe_path,
            installed=True,
            genre="Custom",
            description="",
            background_color="#1a1a1a",
            icon="application-x-executable",
        )
        with self._lock:
            self._games[game_id] = game
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO games
            (id, name, slug, install_path, installed, genre,
             description, background_color, icon, size_bytes, last_played)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            game.id, game.name, game.slug, game.install_path,
            1, game.genre, game.description,
            game.background_color, game.icon, 0, 0,
        ))
        conn.commit()
        return game

    def refresh_async(self, callback: Callable[[], None] | None = None) -> None:
        """Re-scan the filesystem in a background thread."""
        def _worker():
            self._scan()
            if callback:
                callback()
        threading.Thread(target=_worker, daemon=True).start()
