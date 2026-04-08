"""
GameCard — GTK4 widget representing a single game in the library grid.
"""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk, Pango

from bnetlauncher.game_manager import Game
from bnetlauncher.gtk_compat import css_provider_load_string


class GameCard(Gtk.Box):
    """
    A pressable card showing the game banner, name, status, and a play button.
    Emits 'game-selected' signal with the game id.
    """

    def __init__(self, game: Game) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.game = game
        self._build()

    def _build(self) -> None:
        self.add_css_class("bnet-game-card")
        self.set_size_request(220, 300)

        # ── Banner area ────────────────────────────────────────────────
        banner = Gtk.Box()
        banner.set_size_request(220, 180)
        banner.add_css_class("bnet-game-banner")
        banner.set_overflow(Gtk.Overflow.HIDDEN)

        # Coloured placeholder; real art would go here via Gdk.Texture
        banner_bg = Gtk.Label()
        banner_bg.add_css_class("bnet-banner-placeholder")
        # Use the game's background_color as inline CSS
        provider = Gtk.CssProvider()
        css_provider_load_string(
            provider,
            f".bnet-banner-placeholder-{self.game.id} "
            f"{{ background-color: {self.game.background_color}; }}",
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
        )
        banner_bg.add_css_class(f"bnet-banner-placeholder-{self.game.id}")
        banner_bg.set_hexpand(True)
        banner_bg.set_vexpand(True)

        # Game icon / label in banner
        icon_label = Gtk.Label(label=self.game.name[:3].upper())
        icon_label.add_css_class("bnet-banner-icon-label")

        overlay = Gtk.Overlay()
        overlay.set_child(banner_bg)
        overlay.add_overlay(icon_label)
        banner.append(overlay)

        # Installed indicator dot
        if self.game.installed:
            dot = Gtk.Label(label="●")
            dot.add_css_class("bnet-installed-dot")
            dot.set_halign(Gtk.Align.END)
            dot.set_valign(Gtk.Align.START)
            dot.set_margin_top(8)
            dot.set_margin_end(8)
            overlay.add_overlay(dot)

        self.append(banner)

        # ── Info row ───────────────────────────────────────────────────
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.add_css_class("bnet-card-info")
        info.set_margin_top(10)
        info.set_margin_bottom(10)
        info.set_margin_start(12)
        info.set_margin_end(12)

        name_label = Gtk.Label(label=self.game.name)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.add_css_class("bnet-card-name")

        genre_label = Gtk.Label(label=self.game.genre)
        genre_label.set_halign(Gtk.Align.START)
        genre_label.add_css_class("bnet-card-genre")

        info.append(name_label)
        info.append(genre_label)
        self.append(info)

        # ── Play / Install button ──────────────────────────────────────
        btn_label = "PLAY" if self.game.installed else "INSTALL"
        self._play_btn = Gtk.Button(label=btn_label)
        self._play_btn.add_css_class("bnet-play-btn")
        if self.game.installed:
            self._play_btn.add_css_class("bnet-play-btn-installed")
        else:
            self._play_btn.add_css_class("bnet-play-btn-notinstalled")
        self._play_btn.set_margin_start(12)
        self._play_btn.set_margin_end(12)
        self._play_btn.set_margin_bottom(12)
        self.append(self._play_btn)

        # ── Hover gesture ──────────────────────────────────────────────
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        # Click on banner selects the game (don't steal from button)
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_card_clicked)
        banner.add_controller(click)

    # ------------------------------------------------------------------

    def connect_play(self, callback) -> None:
        """callback(game) called when Play button is pressed."""
        self._play_btn.connect("clicked", lambda _: callback(self.game))

    def connect_select(self, callback) -> None:
        """callback(game) called when the card body is clicked."""
        self._on_select = callback

    def _on_card_clicked(self, gesture, n, x, y) -> None:
        if hasattr(self, "_on_select"):
            self._on_select(self.game)

    def _on_enter(self, *_) -> None:
        self.add_css_class("bnet-card-hover")

    def _on_leave(self, *_) -> None:
        self.remove_css_class("bnet-card-hover")

    def set_playing(self, playing: bool) -> None:
        if playing:
            self._play_btn.set_label("PLAYING")
            self._play_btn.set_sensitive(False)
        else:
            self._play_btn.set_label("PLAY" if self.game.installed else "INSTALL")
            self._play_btn.set_sensitive(True)
