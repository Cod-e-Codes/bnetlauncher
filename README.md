# bnetlauncher

A recreation of the Battle.net launcher for Linux with native
Wayland support and Wine/Proton game management.

## Features

- **Wayland-native** — runs as a first-class GTK4/libadwaita Wayland client.
  Falls back to XWayland automatically on X11 sessions.
- **Resize-safe game launching** — applies a layered set of Wine environment
  configurations that prevent the crash loop that happens when a game tries
  to call `ChangeDisplaySettings()` under XWayland.
- **Wine/Proton integration** — auto-detects system Wine and Steam Proton
  installations. Per-game prefixes. esync/fsync/DXVK/FSR support.
- **Battle.net game catalogue** — detects all major Blizzard titles installed
  in Wine prefixes and user-configured directories.
- **Optional Blizzard API** — connect your Battle.net developer credentials
  for live metadata. Works offline without credentials.
- **Hub pages** — **Home** (library stats, quick actions), **Friends** (sign-in
  + open Battle.net; friend APIs not wired yet), **Shop** and **News** (links
  open in your browser, WSL-aware).
- **Settings persistence** — all preferences stored in
  `~/.config/bnetlauncher/config.json`.

## Repository layout

The tree is flat at the top level (no duplicate `bnetlauncher/bnetlauncher/` wrapper):

```
.
├── pyproject.toml
├── README.md
├── LICENSE
├── install.sh
├── scripts/
│   └── check_imports.py   # optional smoke test (imports + GTK)
└── bnetlauncher/          # Python package (see Architecture for full file list)
```

## Requirements

| Package | Purpose |
|---------|---------|
| Python 3.10+ | Runtime (3.10 matches Ubuntu 22.04 LTS; 3.11+ also fine) |
| `python3-gi` | GTK4 Python bindings |
| `gir1.2-gtk-4.0` | GTK4 typelib |
| `gir1.2-adw-1` | libadwaita typelib |
| `wine` / `wine64` | Windows game compatibility |
| `xwayland` | XWayland for Wine (most compositors bundle this) |

Optional: `winetricks`, `dxvk`, Proton (from Steam)

**Distro versions:** The code adapts to older GTK/libadwaita (tested on Ubuntu 22.04: GTK 4.6, libadwaita 1.1). Newer distros use the same code paths with newer APIs where available. `style.css` sticks to properties GTK’s theme parser understands on 4.6 (avoid web-only CSS such as `justify-content` on buttons).

## Installation

```bash
git clone https://github.com/Cod-e-Codes/bnetlauncher
cd bnetlauncher
bash install.sh
```

`install.sh` detects your distro (Ubuntu/Debian/Fedora/Arch/openSUSE) and
installs system packages before installing the Python package with `pip`.

**Manual install:**

```bash
# Ubuntu / Debian
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 wine wine64 xwayland

# Arch / Manjaro
sudo pacman -S python-gobject gtk4 libadwaita wine xorg-xwayland

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita wine xorg-x11-server-Xwayland

pip install --user -e .
```

**Packaging note:** The project uses `setuptools.build_meta` as the build backend (PEP 517). Use a current `pip`/`setuptools` if editable installs fail with a missing `build_editable` hook.

## Developing on Windows

This application is **Linux-only** (GTK4/Wayland). On Windows you can still:

1. **Sanity-check syntax:** `python -m compileall -q bnetlauncher`
2. **Install the package:** `pip install -e .` (confirms `pyproject.toml` / packaging)
3. **Run the real UI under WSL2** (Ubuntu 22.04 or newer recommended):

   ```bash
   sudo apt update
   sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 python3-pip
   cd /mnt/c/Users/YOU/Projects/bnetlauncher   # adjust path
   python3 -m pip install --user --upgrade pip setuptools wheel
   pip3 install --user -e .
   python3 scripts/check_imports.py
   bnetlauncher
   ```

   Run these commands **inside WSL** (after typing `wsl` in PowerShell if needed), not in Windows PowerShell — `apt`, `python3`, and `/mnt/c/...` are Linux-only.

   WSLg provides a display server on recent Windows 10/11; you may see harmless graphics-driver messages in the terminal.

   After **Sign In**, if the browser reports a connection error to `localhost:6547`, see the OAuth notes under [Battle.net API credentials](#battle-net-api-credentials-optional).

## Usage

```bash
bnetlauncher
```

Or launch from your desktop application grid — the installer places a
`.desktop` file in `~/.local/share/applications/`.

Use the **sidebar** to switch between **Home**, **Games**, **Friends**, **Shop**, and **News**. The header **search** bar applies only on **Games** (it hides on other pages).

### Battle.net API credentials (optional)

1. Register at <https://develop.battle.net> and create an application (confidential client with a client secret).
2. Set the **redirect URI** to exactly **`http://localhost:6547/callback`** — scheme, host, port, and path must match (no `https`, no trailing slash).
3. In the launcher, open **Settings → Authentication**, enter **Client ID** and **Client Secret**, and choose your **region** if needed.
4. Click **Sign In**. A browser opens; after you approve access, the launcher receives the callback on **port 6547** and exchanges the code for tokens.

**Account button:** After a successful sign-in (or when valid tokens are already saved), the header shows **Sign Out** instead of **Sign In**. Click **Sign Out** to clear stored tokens on this device; you can sign in again anytime.

**OAuth behaviour:** The local callback server listens on **`0.0.0.0:6547`** so that **WSL2** can receive the redirect when the browser runs on Windows (localhost forwarding from Windows into the Linux VM).

**Opening links under WSL / headless Linux:** WSL must be able to run Windows **`.exe`** helpers ( **[interop] enabled=true** in `/etc/wsl.conf`, then **`wsl --shutdown`** from Windows). If you run **`/mnt/c/Windows/System32/rundll32.exe`** in bash and see **`cannot execute binary file: Exec format error`**, interop is off — Windows browser launch is skipped and the app uses **Linux** handlers instead: **`xdg-open`**, **`gio open`**, **`firefox`**, **`chromium`**, etc. Install one with e.g. **`sudo apt install firefox`**. **`wslview`** also needs interop unless it is implemented as a pure Linux script.

When interop works, the launcher tries the Windows host first (**`rundll32`**, PowerShell, **`cmd /c start`**, **`explorer`**), then **`wslview`**, Python’s **`webbrowser`**, and the Linux helpers above. Only `webbrowser.open()` returning **`True`** counts as success ( **`None`** does not). If auto-open fails, the URL is printed to **`stderr`**; for **Sign In**, the local callback server **stays running** so you can paste that URL into any browser and complete OAuth.

If sign-in times out or the browser shows “connection refused” on the callback, use a current **Windows 11 + WSL2** stack with localhost forwarding enabled, run the app on **native Linux**, or ensure nothing else is bound to port **6547**.

**Windows shell gotcha:** Do not paste `pip install setuptools>=68` into **cmd.exe** unquoted — `>` is treated as redirection and can create junk files like `=68`. Use **WSL/bash** for the commands in this README, or quote the requirement (`"setuptools>=68"`).

Without credentials the launcher still works for local library and Wine management; online-style features that need Blizzard APIs require sign-in.

### Installing games

This launcher does not download game binaries itself. **INSTALL** opens the
Blizzard **download page** for that title (in your browser). For games like
**World of Warcraft**, that page normally downloads **`Battle.net-Setup.exe`**
(the Battle.net desktop app installer) — **not** a standalone WoW installer.
That is Blizzard's intended flow: install Battle.net, sign in, pick the game
there, then let it download the actual game data.

Run **`Battle.net-Setup.exe`** with Wine from the directory where Firefox saved
it, for example: **`wine ~/Downloads/Battle.net-Setup.exe`**. After Battle.net
is installed, use it to install WoW (or any title), then click **refresh** in
bnetlauncher so the library rescans.

If **Battle.net.exe** / **Battle.net Launcher.exe** is already present under
`~/.wine`, your **Wine prefix directory**, or a **custom game path** whose root
contains **`drive_c`**, **INSTALL** can start that app in Wine for you while
the download page opens.

If no browser opens, check the terminal: the launcher prints the **exact URL** to
`stderr` so you can paste it into a browser manually. Install **`wslu`** / **`wslview`**
on WSL if you want a lightweight “open in Windows default browser” helper.

### Adding games manually

If your game is installed outside a Wine prefix, click the "⟳" refresh button
or go to **Settings → Wine / Proton** and add the directory under
"Custom Game Paths".

## Architecture

```
bnetlauncher/                 # Python package (under repo root)
├── main.py          — Entry point; configures Wayland env before GTK loads
├── app.py           — Adw.Application subclass; CSS loading, app actions
├── gtk_compat.py    — CSS loading / API shims for older GTK (e.g. 4.6)
├── window.py        — Main window; toasts use Pango-safe (escaped) titles for URLs/errors
├── auth.py          — Battle.net OAuth2; callback on 0.0.0.0:6547; open_default_browser (WSL→Windows host first, then wslview/webbrowser/xdg-open)
├── config.py        — JSON config with XDG paths; module-level singleton
├── game_manager.py  — Game catalogue, disk scanning, SQLite state
├── wine_runner.py   — Wine/Proton launch with Wayland resize mitigations
└── ui/
    ├── game_card.py — GTK4 game card widget (FlowBox child)
    ├── hub_pages.py — Home / Friends / Shop / News stack pages
    ├── sidebar.py   — Navigation sidebar with toggle-button group
    ├── settings.py  — Preferences (Adw.PreferencesDialog or PreferencesWindow + fallbacks on older libadwaita)
    └── style.css    — Battle.net dark theme for GTK4
```

## Source archive

To create a distributable tarball from a clean tree (excludes `__pycache__` and local install metadata):

```bash
tar -czf bnetlauncher.tar.gz \
  --exclude='__pycache__' \
  --exclude='*.egg-info' \
  pyproject.toml README.md LICENSE install.sh bnetlauncher scripts
```

## Wayland / Resize Safety Details

The crash on screen resize or fullscreen toggle under Wayland is a known
interaction between XWayland and Wine's `ChangeDisplaySettings` call.

**Mitigations applied in `wine_runner.py`:**

| Environment variable | Effect |
|---------------------|--------|
| `WINE_FULLSCREEN_FAKE_FULLSCREEN=1` | Intercepts display mode changes; returns success without reconfiguring XWayland |
| `WINE_SIMULATE_WRITECOMBINE=0` | Disables write-combine simulation that can cause page-mapping crashes |
| `WINE_LARGE_ADDRESS_AWARE=1` | Allows 32-bit games to access >2 GB address space |
| `WINEESYNC=1` / `WINEFSYNC=1` | Reduces kernel lock contention |
| `DXVK_ASYNC=1` | Prevents pipeline stall hangs that look like crashes |
| `SDL_VIDEODRIVER=x11` | Forces SDL games to use XWayland not a Wayland socket |
| `WAYLAND_DISPLAY` (unset) | Prevents Wine child processes from attempting native Wayland |

**Optional: Virtual Desktop mode**

Settings → Display → Virtual Desktop: runs the game inside a Wine explorer
window. Completely eliminates resize crashes at the cost of desktop
integration (alt-tab, etc.).

## Configuration file

`~/.config/bnetlauncher/config.json` — human-editable JSON:

```json
{
  "bnet_client_id": "...",
  "bnet_client_secret": "...",
  "wine_executable": "wine64",
  "dxvk_enabled": true,
  "esync_enabled": true,
  "fsync_enabled": true,
  "fake_fullscreen": true,
  "force_borderless": true,
  "virtual_desktop": false,
  "virtual_desktop_res": "1920x1080",
  "fsr_enabled": false,
  "custom_game_paths": ["/mnt/games/blizzard"]
}
```

## License

MIT — see LICENSE.
