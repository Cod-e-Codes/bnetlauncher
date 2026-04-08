"""
GTK4 Application class for bnetlauncher.
"""
import os
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from bnetlauncher.gtk_compat import css_provider_load_string  # noqa: E402


CSS_PATH = Path(__file__).parent / "ui" / "style.css"

# DEFAULT_FLAGS exists in GLib ≥2.74; Ubuntu 22.04 ships older introspection.
_APPLICATION_FLAGS = getattr(
    Gio.ApplicationFlags,
    "DEFAULT_FLAGS",
    Gio.ApplicationFlags.FLAGS_NONE,
)


class BNetApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="com.bnetlauncher.App",
            flags=_APPLICATION_FLAGS,
        )
        self.connect("activate", self._on_activate)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_activate(self, app: "BNetApplication") -> None:
        self._load_css()
        self._build_actions()

        from bnetlauncher.window import MainWindow

        win = MainWindow(application=self)
        win.present()

    # ------------------------------------------------------------------
    # CSS
    # ------------------------------------------------------------------

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        if CSS_PATH.exists():
            provider.load_from_path(str(CSS_PATH))
        else:
            css_provider_load_string(provider, self._fallback_css())

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    @staticmethod
    def _fallback_css() -> str:
        return """
        .bnet-sidebar { background-color: #06101e; }
        .bnet-game-card { background-color: #0d1b2a; border-radius: 6px; }
        """

    # ------------------------------------------------------------------
    # App-level actions
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        actions = [
            ("quit", self._on_quit, ["<primary>q"]),
            ("about", self._on_about, None),
        ]
        for name, callback, accels in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def _on_quit(self, *_) -> None:
        self.quit()

    def _on_about(self, *_) -> None:
        dialog = Adw.AboutDialog(
            application_name="bnetlauncher",
            application_icon="applications-games",
            developer_name="bnetlauncher",
            version="1.0.0",
            comments=(
                "Third-party launcher for Blizzard titles on Linux. Per-game "
                "Wine prefixes, Wayland-friendly launches. Not affiliated with Blizzard."
            ),
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(self.get_active_window())
