#!/usr/bin/env bash
# bnetlauncher install script
# Installs system dependencies and the launcher for the current user.
set -euo pipefail

APP="bnetlauncher"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="${HOME}/.local"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

# ── Colour output ──────────────────────────────────────────────────────
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red() { printf '\033[31m%s\033[0m\n' "$*"; }
info() { printf '  → %s\n' "$*"; }

green "=== bnetlauncher installer ==="
echo ""

# ── Detect distro ─────────────────────────────────────────────────────
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "${ID}"
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
info "Detected distribution: ${DISTRO}"

# ── Install system dependencies ────────────────────────────────────────
install_deps() {
    echo ""
    yellow "Installing system dependencies…"
    case "${DISTRO}" in
        ubuntu|debian|linuxmint|pop)
            sudo apt-get update -qq
            sudo apt-get install -y \
                python3 \
                python3-gi \
                python3-gi-cairo \
                gir1.2-gtk-4.0 \
                gir1.2-adw-1 \
                libadwaita-1-dev \
                wine \
                wine64 \
                winetricks \
                xwayland
            ;;
        fedora|rhel|centos)
            sudo dnf install -y \
                python3 \
                python3-gobject \
                gtk4 \
                libadwaita \
                wine \
                xorg-x11-server-Xwayland
            ;;
        arch|manjaro|endeavouros|garuda)
            sudo pacman -Sy --noconfirm \
                python \
                python-gobject \
                gtk4 \
                libadwaita \
                wine \
                winetricks \
                xorg-xwayland
            ;;
        opensuse*|suse)
            sudo zypper install -y \
                python3 \
                python3-gobject \
                typelib-1_0-Gtk-4_0 \
                typelib-1_0-Adw-1 \
                wine \
                xwayland
            ;;
        *)
            yellow "Unknown distro '${DISTRO}'. Attempting apt-get (may fail)."
            sudo apt-get install -y \
                python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 wine wine64 xwayland || true
            ;;
    esac
    green "System dependencies installed."
}

# ── Check if GTK4 bindings are already present ─────────────────────────
check_gtk4() {
    python3 -c "
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Adw
" 2>/dev/null
}

if check_gtk4; then
    info "GTK4 Python bindings already available; skipping system install."
else
    install_deps
fi

# ── Install the Python package ─────────────────────────────────────────
echo ""
yellow "Installing bnetlauncher Python package…"
pip3 install --user --break-system-packages -e "${REPO_DIR}" 2>/dev/null \
    || pip3 install --user -e "${REPO_DIR}"
green "Python package installed."

# ── Desktop entry ──────────────────────────────────────────────────────
echo ""
yellow "Installing desktop entry…"
mkdir -p "${DESKTOP_DIR}" "${ICON_DIR}"

# Create a simple SVG icon
cat > "${ICON_DIR}/bnetlauncher.svg" << 'SVGEOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#08111f"/>
  <circle cx="32" cy="32" r="20" fill="none" stroke="#148eff" stroke-width="3"/>
  <circle cx="32" cy="32" r="10" fill="#148eff" opacity="0.8"/>
  <path d="M32 12 L32 52 M12 32 L52 32" stroke="#148eff" stroke-width="1.5" opacity="0.4"/>
</svg>
SVGEOF

cat > "${DESKTOP_DIR}/bnetlauncher.desktop" << DESKTOPEOF
[Desktop Entry]
Type=Application
Name=bnetlauncher
GenericName=Blizzard games (Wine)
Comment=Third-party Blizzard game launcher for Linux with Wayland support
Exec=${HOME}/.local/bin/bnetlauncher
Icon=bnetlauncher
Terminal=false
Categories=Game;
Keywords=blizzard;wow;diablo;overwatch;hearthstone;starcraft;
StartupWMClass=com.bnetlauncher.App
DESKTOPEOF

# Update icon cache if on a desktop system
command -v update-desktop-database &>/dev/null \
    && update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
command -v gtk-update-icon-cache &>/dev/null \
    && gtk-update-icon-cache -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

green "Desktop entry installed."

# ── Validate Wine ──────────────────────────────────────────────────────
echo ""
yellow "Checking Wine installation…"
if command -v wine64 &>/dev/null || command -v wine &>/dev/null; then
    WINE_BIN=$(command -v wine64 || command -v wine)
    WINE_VER=$("${WINE_BIN}" --version 2>/dev/null || echo "unknown")
    green "Wine found: ${WINE_VER}"
else
    red "Wine not found! Install wine or wine64 to run games."
fi

# ── Optional: DXVK ───────────────────────────────────────────────────
echo ""
yellow "Checking for DXVK…"
if command -v winetricks &>/dev/null; then
    info "winetricks is available. Run 'winetricks dxvk' in a game prefix to install DXVK."
else
    info "Install winetricks for easy DXVK installation."
fi

# ── Done ───────────────────────────────────────────────────────────────
echo ""
green "=== Installation complete ==="
echo ""
echo "  Launch with:  bnetlauncher"
echo "  Or search for 'bnetlauncher' in your application launcher."
echo ""
echo "  Configuration: ~/.config/bnetlauncher/config.json"
echo "  Game data:     ~/.local/share/bnetlauncher/"
echo ""
echo "  To use Battle.net APIs, register at https://develop.battle.net"
echo "  and enter your client ID/secret in Settings."
echo ""
