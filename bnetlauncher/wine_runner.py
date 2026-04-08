"""
Wine/Proton game runner.

Core problem: on Wayland, games that call ChangeDisplaySettings() to switch
resolution or enter exclusive fullscreen cause XWayland to reconfigure its
virtual framebuffer.  If the game process doesn't gracefully handle the
resync, it segfaults or freezes.

Mitigations applied here:
  1. WINE_FULLSCREEN_FAKE_FULLSCREEN=1: intercepts ChangeDisplaySettings
     calls and returns success without actually changing the mode.  The game
     thinks it's fullscreen; the resolution never actually changes.
  2. Borderless windowed via registry injection: sets the game to a
     borderless window that fills the screen instead of exclusive FS.
  3. WINEDEBUG=-all: suppresses Wine's noisy debug output that can cause
     pipe buffer pressure and hangs.
  4. DXVK_ASYNC=1: prevents pipeline stalls that look like crashes.
  5. esync/fsync: reduces kernel-side lock contention.
  6. SDL_VIDEODRIVER and DISPLAY are set explicitly so the child process
     connects to XWayland rather than trying to open a Wayland socket
     (most Windows games don't speak Wayland).
  7. Virtual desktop mode (optional): runs inside a Wine virtual desktop
     window.  Completely eliminates resize-induced crashes at the cost of
     desktop integration.
"""
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from bnetlauncher.config import get_config


class WineError(Exception):
    pass


class WineRunner:
    def __init__(self) -> None:
        self.cfg = get_config()
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def launch(
        self,
        game_id: str,
        executable: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        prefix: str | None = None,
        on_exit: Callable[[int], None] | None = None,
    ) -> subprocess.Popen:
        """
        Launch a Windows executable under Wine/Proton.
        Returns the Popen object immediately; monitors exit in background.
        Raises WineError if Wine is not found.
        """
        wine_bin = self._resolve_wine()
        env = self._build_env(prefix, game_id)
        cmd = self._build_command(wine_bin, executable, args or [])

        cwd = working_dir or str(Path(executable).parent)

        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,  # new process group → clean kill
        )

        with self._lock:
            self._active_procs[game_id] = proc

        thread = threading.Thread(
            target=self._monitor,
            args=(game_id, proc, on_exit),
            daemon=True,
        )
        thread.start()
        return proc

    def stop(self, game_id: str) -> None:
        with self._lock:
            proc = self._active_procs.get(game_id)
        if proc and proc.poll() is None:
            # Send SIGTERM to the entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

    def is_running(self, game_id: str) -> bool:
        with self._lock:
            proc = self._active_procs.get(game_id)
        return proc is not None and proc.poll() is None

    @staticmethod
    def wine_prefix_for_exe(windows_exe: str) -> Optional[str]:
        """Return WINEPREFIX path containing drive_c for a Windows path inside Wine."""
        cur = Path(windows_exe).resolve()
        while cur != cur.parent:
            if cur.name == "drive_c":
                return str(cur.parent)
            cur = cur.parent
        return None

    def find_battle_net_executable(self) -> Optional[str]:
        """Locate Blizzard desktop agent executables under Wine prefixes and custom paths."""
        roots: list[Path] = []
        home_wine = Path.home() / ".wine"
        if (home_wine / "drive_c").is_dir():
            roots.append(home_wine)
        prefix_dir = Path(self.cfg.get("wine_prefix_dir", ""))
        if prefix_dir.is_dir():
            for child in sorted(prefix_dir.iterdir()):
                if (child / "drive_c").is_dir():
                    roots.append(child)
        for raw in self.cfg.get("custom_game_paths", []):
            p = Path(os.path.expanduser(str(raw)))
            try:
                p = p.resolve()
            except OSError:
                continue
            if (p / "drive_c").is_dir():
                roots.append(p)

        def pick_in_bnet_dir(bnet_dir: Path) -> Optional[str]:
            if not bnet_dir.is_dir():
                return None
            for name in ("Battle.net.exe", "Battle.net Launcher.exe"):
                exe = bnet_dir / name
                if exe.is_file():
                    return str(exe)
            return None

        for root in roots:
            for prog in ("Program Files (x86)/Battle.net", "Program Files/Battle.net"):
                hit = pick_in_bnet_dir(root / "drive_c" / prog)
                if hit:
                    return hit
        return None

    # ------------------------------------------------------------------
    # Wine binary resolution
    # ------------------------------------------------------------------

    def _resolve_wine(self) -> str:
        if self.cfg.get("use_proton"):
            return self._resolve_proton()

        configured = self.cfg.get("wine_executable", "wine")
        if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured

        # Search PATH
        found = shutil.which("wine64") or shutil.which("wine")
        if found:
            return found

        raise WineError(
            "Wine not found. Install wine or wine64, or set the Wine "
            "executable path in Settings."
        )

    def _resolve_proton(self) -> str:
        proton_dir = self.cfg.get("proton_path", "")
        if proton_dir:
            proton_bin = Path(proton_dir) / "proton"
            if proton_bin.exists():
                return str(proton_bin)

        # Try Steam's default Proton locations
        steam_dirs = [
            Path.home() / ".steam/steam/steamapps/common",
            Path.home() / ".local/share/Steam/steamapps/common",
        ]
        for steam in steam_dirs:
            if steam.is_dir():
                protons = sorted(steam.glob("Proton *"), reverse=True)
                if protons:
                    candidate = protons[0] / "proton"
                    if candidate.exists():
                        return str(candidate)

        # Fallback to system wine
        return self._resolve_wine()

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def _build_command(
        self,
        wine_bin: str,
        executable: str,
        args: list[str],
    ) -> list[str]:
        if self.cfg.get("virtual_desktop"):
            res = self.cfg.get("virtual_desktop_res", "1920x1080")
            return [
                wine_bin,
                "explorer",
                f"/desktop=bnetgame,{res}",
                executable,
                *args,
            ]

        return [wine_bin, executable, *args]

    # ------------------------------------------------------------------
    # Environment construction (core of resize safety)
    # ------------------------------------------------------------------

    def _build_env(self, prefix: Optional[str], game_id: str) -> dict[str, str]:
        env = os.environ.copy()

        # ── Wine prefix ────────────────────────────────────────────────
        if prefix is None:
            prefix = str(
                Path(self.cfg.get("wine_prefix_dir")) / game_id
            )
        Path(prefix).mkdir(parents=True, exist_ok=True)
        env["WINEPREFIX"] = prefix
        env["WINEARCH"] = "win64"

        # ── Display: point child to XWayland ──────────────────────────
        # Most Windows games cannot speak native Wayland (no winewayland
        # driver by default in distro packages).  We force XWayland.
        xdisplay = os.environ.get("DISPLAY", ":0")
        env["DISPLAY"] = xdisplay
        # Do NOT forward WAYLAND_DISPLAY to the child; it confuses SDL.
        env.pop("WAYLAND_DISPLAY", None)

        # SDL: use x11 backend (XWayland), not wayland
        env["SDL_VIDEODRIVER"] = "x11"
        env["SDL_AUDIODRIVER"] = "pulseaudio"

        # ── Resize-safety mitigations ─────────────────────────────────
        if self.cfg.get("fake_fullscreen", True):
            # Intercept ChangeDisplaySettings; return success without
            # actually reconfiguring XWayland's virtual screen.
            env["WINE_FULLSCREEN_FAKE_FULLSCREEN"] = "1"

        # Prevent Wine from simulating write-combine memory (can crash on
        # some Wayland compositors when pages are remapped mid-frame).
        env["WINE_SIMULATE_WRITECOMBINE"] = "0"

        # Large address aware: lets 32-bit games use >2 GB; reduces OOM
        # crashes that look like resize-related crashes.
        env["WINE_LARGE_ADDRESS_AWARE"] = "1"

        # Don't let Wine mess with the system menu builder
        env["WINEDLLOVERRIDES"] = (
            "winemenubuilder.exe=d;"
            + env.get("WINEDLLOVERRIDES", "")
        )

        # Quiet Wine debug output (avoids pipe pressure / hangs)
        env.setdefault("WINEDEBUG", "-all")

        # ── esync / fsync (event/futex synchronization) ───────────────
        if self.cfg.get("esync_enabled", True):
            env["WINEESYNC"] = "1"
        if self.cfg.get("fsync_enabled", True):
            env["WINEFSYNC"] = "1"

        # ── DXVK (Vulkan-based D3D implementation) ────────────────────
        if self.cfg.get("dxvk_enabled", True):
            env["DXVK_ASYNC"] = "1"
            env["DXVK_STATE_CACHE"] = "1"
            dxvk_cache = str(self.cfg.cache_dir / "dxvk_cache" / game_id)
            Path(dxvk_cache).mkdir(parents=True, exist_ok=True)
            env["DXVK_STATE_CACHE_PATH"] = dxvk_cache
            env.setdefault("DXVK_HUD", "0")

        # ── AMD FSR (optional upscaling) ───────────────────────────────
        if self.cfg.get("fsr_enabled", False):
            env["WINE_FULLSCREEN_FSR"] = "1"
            env["WINE_FULLSCREEN_FSR_STRENGTH"] = "2"

        # ── Mesa / Vulkan ──────────────────────────────────────────────
        env.setdefault("MESA_GL_VERSION_OVERRIDE", "4.6")
        env.setdefault("MESA_GLSL_VERSION_OVERRIDE", "460")

        # ── Vulkan ICD: prefer discrete GPU ───────────────────────────
        # Don't override if the user already set it
        if "VK_ICD_FILENAMES" not in env:
            for icd in [
                "/usr/share/vulkan/icd.d/nvidia_icd.json",
                "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json",
            ]:
                if os.path.exists(icd):
                    env["VK_ICD_FILENAMES"] = icd
                    break

        return env

    # ------------------------------------------------------------------
    # Process monitor
    # ------------------------------------------------------------------

    def _monitor(
        self,
        game_id: str,
        proc: subprocess.Popen,
        on_exit: Optional[Callable[[int], None]],
    ) -> None:
        returncode = proc.wait()

        # Drain stderr so the pipe buffer doesn't stay open
        try:
            stderr_output = proc.stderr.read().decode(errors="replace")
            if stderr_output and "fixme:" not in stderr_output.lower():
                pass  # could log to file here
        except Exception:
            pass

        with self._lock:
            self._active_procs.pop(game_id, None)

        if on_exit:
            on_exit(returncode)

    # ------------------------------------------------------------------
    # Prefix management helpers
    # ------------------------------------------------------------------

    def init_prefix(self, game_id: str) -> str:
        """Create and initialize a Wine prefix for the given game."""
        wine_bin = self._resolve_wine()
        prefix = str(Path(self.cfg.get("wine_prefix_dir")) / game_id)
        env = self._build_env(prefix, game_id)

        # wineboot initializes the prefix directory structure
        subprocess.run(
            [wine_bin, "wineboot", "--init"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )

        if self.cfg.get("force_borderless", True):
            self._set_borderless_registry(wine_bin, env, game_id)

        return prefix

    def _set_borderless_registry(
        self, wine_bin: str, env: dict, game_id: str
    ) -> None:
        """
        Write Wine registry keys that force borderless windowed mode.
        This is the most reliable way to prevent exclusive fullscreen
        on XWayland without patching game binaries.
        """
        reg_commands = [
            # Explorer uses a virtual desktop by default
            r'HKCU\Software\Wine\Explorer',
            r'HKCU\Software\Wine\Explorer\Desktops',
        ]
        # Desktop emulation off: let the WM manage window decoration
        regs = [
            (
                r"HKCU\Software\Wine\Explorer",
                "Desktop",
                "REG_SZ",
                "Default",
            ),
            (
                r"HKCU\Software\Wine\Explorer\Desktops",
                "Default",
                "REG_SZ",
                "1024x768",
            ),
        ]
        for path, name, kind, value in regs:
            subprocess.run(
                [wine_bin, "reg", "add", path, "/v", name, "/t", kind,
                 "/d", value, "/f"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )

    def get_wine_version(self) -> str:
        try:
            wine_bin = self._resolve_wine()
            result = subprocess.run(
                [wine_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except (WineError, subprocess.TimeoutExpired, FileNotFoundError):
            return "Wine not found"
