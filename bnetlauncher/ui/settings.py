"""
Settings UI: Adw.PreferencesDialog on libadwaita ≥1.2, else PreferencesWindow + ActionRow fallbacks (Ubuntu 22.04).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from bnetlauncher.config import get_config
from bnetlauncher.wine_runner import WineRunner

_HAS_PREF_DIALOG = hasattr(Adw, "PreferencesDialog")
_HAS_ENTRY_ROW = hasattr(Adw, "EntryRow")
_HAS_PASSWORD_ENTRY_ROW = hasattr(Adw, "PasswordEntryRow")
_HAS_SWITCH_ROW = hasattr(Adw, "SwitchRow")

_PrefBase = Adw.PreferencesDialog if _HAS_PREF_DIALOG else Adw.PreferencesWindow


def _text_preferences_row(
    title: str,
    text: str,
    *,
    secret: bool,
    on_changed,
) -> Gtk.Widget:
    if _HAS_ENTRY_ROW:
        if secret and _HAS_PASSWORD_ENTRY_ROW:
            row = Adw.PasswordEntryRow(title=title)
        else:
            row = Adw.EntryRow(title=title)
        row.set_text(text)

        def _save(_row) -> None:
            on_changed(_row.get_text())

        row.connect("changed", _save)
        return row

    row = Adw.ActionRow()
    row.set_title(title)
    entry = Gtk.PasswordEntry() if secret else Gtk.Entry()
    entry.set_text(text)
    entry.set_hexpand(True)
    entry.set_width_chars(24)

    def _save_editable(_entry, _pspec) -> None:
        on_changed(_entry.get_text())

    entry.connect("notify::text", _save_editable)
    row.add_suffix(entry)
    return row


def _switch_preferences_row(
    title: str,
    subtitle: str,
    active: bool,
    on_changed,
) -> Gtk.Widget:
    if _HAS_SWITCH_ROW:
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(active)
        row.connect(
            "notify::active",
            lambda r, _: on_changed(r.get_active()),
        )
        return row

    row = Adw.ActionRow()
    row.set_title(title)
    row.set_subtitle(subtitle)
    sw = Gtk.Switch()
    sw.set_active(active)
    sw.set_valign(Gtk.Align.CENTER)
    sw.connect("notify::active", lambda w, _: on_changed(w.get_active()))
    row.add_suffix(sw)
    return row


class SettingsDialog(_PrefBase):
    def __init__(
        self,
        parent: Gtk.Widget,
        *,
        on_library_prefs_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self.cfg = get_config()
        self._on_library_prefs_changed = on_library_prefs_changed
        self.set_title("Preferences")
        self._build()
        if _HAS_PREF_DIALOG:
            self.present(parent)
        else:
            if isinstance(parent, Gtk.Window):
                self.set_transient_for(parent)
            self.set_modal(True)
            self.present()

    def _build(self) -> None:
        self._build_auth_page()
        self._build_library_page()
        self._build_wine_page()
        self._build_display_page()

    def _build_library_page(self) -> None:
        page = Adw.PreferencesPage(
            title="Library",
            icon_name="view-list-symbolic",
        )
        group = Adw.PreferencesGroup(
            title="Catalogue",
            description=(
                "Titles marked as not viable on Linux/Wine (for example some "
                "anti-cheat FPS games) are hidden unless you enable the option below."
            ),
        )

        def _notify_library(visible: bool) -> None:
            self.cfg.set("show_unsupported_games", visible)
            if self._on_library_prefs_changed:
                self._on_library_prefs_changed()

        group.add(
            _switch_preferences_row(
                "Show unsupported titles",
                "List games the catalogue marks as a poor fit for Linux/Wine",
                self.cfg.get("show_unsupported_games", False),
                _notify_library,
            )
        )
        page.add(group)

        paths_group = Adw.PreferencesGroup(
            title="Extra scan folders",
            description=(
                "Directories to search for Blizzard installs (in addition to Wine "
                "prefixes). Add the folder that contains game roots such as "
                "“World of Warcraft” or “Diablo IV” — for example /mnt/g_drive if "
                "WoW is at /mnt/g_drive/World of Warcraft/."
            ),
        )
        self._custom_paths_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        paths_group.add(self._custom_paths_box)
        self._rebuild_custom_path_rows()

        # Plain Gtk.Button is not a PreferencesRow; some libadwaita versions ignore
        # clicks. Use ActionRow + suffix (same pattern as remove buttons on paths).
        add_row = Adw.ActionRow()
        add_row.set_title("Add folder…")
        add_row.set_subtitle("Browse for a directory that contains Blizzard game folders")
        add_btn = Gtk.Button(label="Browse…")
        add_btn.add_css_class("pill")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_scan_folder_clicked)
        add_row.add_suffix(add_btn)
        paths_group.add(add_row)
        page.add(paths_group)

        self.add(page)

    # ------------------------------------------------------------------
    # Auth page
    # ------------------------------------------------------------------

    def _build_auth_page(self) -> None:
        page = Adw.PreferencesPage(
            title="Authentication",
            icon_name="network-server-symbolic",
        )

        group = Adw.PreferencesGroup(
            title="Blizzard developer API",
            description=(
                "Register at https://develop.battle.net to obtain "
                "a client ID and secret."
            ),
        )

        self._client_id_row = _text_preferences_row(
            "Client ID",
            self.cfg.get("bnet_client_id", ""),
            secret=False,
            on_changed=lambda t: self.cfg.set("bnet_client_id", t),
        )
        group.add(self._client_id_row)

        self._client_secret_row = _text_preferences_row(
            "Client Secret",
            self.cfg.get("bnet_client_secret", ""),
            secret=True,
            on_changed=lambda t: self.cfg.set("bnet_client_secret", t),
        )
        group.add(self._client_secret_row)

        region_row = Adw.ComboRow(title="Region")
        regions = Gtk.StringList.new(["us", "eu", "kr", "tw", "cn"])
        region_row.set_model(regions)
        current_region = self.cfg.get("bnet_region", "us")
        regions_list = ["us", "eu", "kr", "tw", "cn"]
        if current_region in regions_list:
            region_row.set_selected(regions_list.index(current_region))
        region_row.connect("notify::selected", self._save_region, regions_list)
        group.add(region_row)

        page.add(group)
        self.add(page)

    def _save_region(self, row, _pspec, regions):
        self.cfg.set("bnet_region", regions[row.get_selected()])

    @staticmethod
    def _norm_scan_path(path: str) -> str:
        p = os.path.normpath(os.path.expanduser(path.strip()))
        try:
            return os.path.abspath(p)
        except OSError:
            return p

    def _get_custom_paths(self) -> list[str]:
        raw = self.cfg.get("custom_game_paths", [])
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for x in raw:
            s = str(x).strip()
            if s:
                out.append(s)
        return out

    def _persist_custom_paths(self, paths: list[str]) -> None:
        seen: set[str] = set()
        unique: list[str] = []
        for p in paths:
            key = self._norm_scan_path(p)
            if key in seen:
                continue
            seen.add(key)
            unique.append(p.strip())
        self.cfg.set("custom_game_paths", unique)
        self._rebuild_custom_path_rows()
        if self._on_library_prefs_changed:
            self._on_library_prefs_changed()

    def _rebuild_custom_path_rows(self) -> None:
        while True:
            child = self._custom_paths_box.get_first_child()
            if child is None:
                break
            self._custom_paths_box.remove(child)

        paths = self._get_custom_paths()
        if not paths:
            empty = Gtk.Label(label="No extra folders. Add one if games live outside Wine prefixes.")
            empty.add_css_class("dim-label")
            empty.set_halign(Gtk.Align.START)
            empty.set_margin_top(6)
            empty.set_margin_bottom(6)
            self._custom_paths_box.append(empty)
            return

        for path in paths:
            row = Adw.ActionRow()
            disp = path
            if len(disp) > 64:
                disp = "…" + disp[-62:]
            row.set_title(disp)
            row.set_subtitle(path)

            rm = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
            rm.add_css_class("flat")
            rm.set_valign(Gtk.Align.CENTER)
            rm.set_tooltip_text("Remove this folder from scanning")
            rm.connect("clicked", self._on_remove_custom_path_clicked, path)
            row.add_suffix(rm)
            self._custom_paths_box.append(row)

    def _on_remove_custom_path_clicked(self, _btn, path: str) -> None:
        paths = [p for p in self._get_custom_paths() if self._norm_scan_path(p) != self._norm_scan_path(path)]
        self._persist_custom_paths(paths)

    def _on_add_scan_folder_clicked(self, _btn) -> None:
        # Modal Gtk dialog is more reliable than FileChooserNative + get_root() on
        # Wayland / older GTK when nested under PreferencesDialog.
        dlg = Gtk.FileChooserDialog(
            title="Add folder to scan for games",
            transient_for=self,
            modal=True,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Add", Gtk.ResponseType.ACCEPT)
        dlg.set_default_response(Gtk.ResponseType.ACCEPT)

        def on_response(dialog: Gtk.FileChooserDialog, response: int) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dialog.get_file()
                if gfile:
                    p = gfile.get_path()
                    if p:
                        paths = list(self._get_custom_paths())
                        np = self._norm_scan_path(p)
                        if not any(self._norm_scan_path(x) == np for x in paths):
                            paths.append(p)
                            self._persist_custom_paths(paths)
            dialog.destroy()

        dlg.connect("response", on_response)
        dlg.present()

    # ------------------------------------------------------------------
    # Wine page
    # ------------------------------------------------------------------

    def _build_wine_page(self) -> None:
        page = Adw.PreferencesPage(
            title="Wine / Proton",
            icon_name="application-x-executable-symbolic",
        )

        info_group = Adw.PreferencesGroup(title="Wine Information")
        runner = WineRunner()
        version = runner.get_wine_version()
        version_row = Adw.ActionRow(
            title="Detected Wine",
            subtitle=version,
        )
        version_row.add_prefix(
            Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic" if version != "Wine not found" else "dialog-warning-symbolic"
            )
        )
        info_group.add(version_row)
        page.add(info_group)

        group = Adw.PreferencesGroup(title="Wine Settings")

        group.add(
            _switch_preferences_row(
                "Use Proton",
                "Prefer Proton over system Wine",
                self.cfg.get("use_proton", False),
                lambda v: self.cfg.set("use_proton", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "esync",
                "Event-based synchronization (recommended)",
                self.cfg.get("esync_enabled", True),
                lambda v: self.cfg.set("esync_enabled", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "fsync",
                "Futex-based synchronization",
                self.cfg.get("fsync_enabled", True),
                lambda v: self.cfg.set("fsync_enabled", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "DXVK",
                "Vulkan-based Direct3D implementation",
                self.cfg.get("dxvk_enabled", True),
                lambda v: self.cfg.set("dxvk_enabled", v),
            )
        )

        page.add(group)
        self.add(page)

    # ------------------------------------------------------------------
    # Display page
    # ------------------------------------------------------------------

    def _build_display_page(self) -> None:
        page = Adw.PreferencesPage(
            title="Display",
            icon_name="video-display-symbolic",
        )

        group = Adw.PreferencesGroup(
            title="Wayland / Resize Safety",
            description=(
                "These settings prevent game crashes when resizing or "
                "switching between fullscreen and windowed mode on Wayland."
            ),
        )

        group.add(
            _switch_preferences_row(
                "Fake Fullscreen",
                "Intercept ChangeDisplaySettings (helps avoid XWayland crashes)",
                self.cfg.get("fake_fullscreen", True),
                lambda v: self.cfg.set("fake_fullscreen", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "Force Borderless Windowed",
                "Use borderless window instead of exclusive fullscreen",
                self.cfg.get("force_borderless", True),
                lambda v: self.cfg.set("force_borderless", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "AMD FSR Upscaling",
                "Enable Wine FSR upscaling support",
                self.cfg.get("fsr_enabled", False),
                lambda v: self.cfg.set("fsr_enabled", v),
            )
        )
        group.add(
            _switch_preferences_row(
                "Virtual Desktop",
                "Run inside a Wine virtual desktop window (max compatibility)",
                self.cfg.get("virtual_desktop", False),
                lambda v: self.cfg.set("virtual_desktop", v),
            )
        )

        res_row = _text_preferences_row(
            "Virtual Desktop Resolution",
            self.cfg.get("virtual_desktop_res", "1920x1080"),
            secret=False,
            on_changed=lambda t: self.cfg.set("virtual_desktop_res", t),
        )
        group.add(res_row)

        page.add(group)
        self.add(page)
