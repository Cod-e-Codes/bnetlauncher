"""
MainWindow: primary application window.

Layout (left → right):
  Sidebar | Main stack (home / games / friends / shop / news / settings)

The games view has a secondary panel split:
  Game grid (scrollable FlowBox) | Game detail panel (right)

Wayland resize note: we connect to the GdkSurface 'notify::width' and
'notify::height' signals via the toplevel surface to handle compositor-driven
size changes gracefully without freezing or crashing.
"""
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from bnetlauncher.auth import BNetAuth, open_default_browser, print_browser_open_hints
from bnetlauncher.config import get_config
from bnetlauncher.game_manager import Game, GameManager
from bnetlauncher import install_health, wow_addons
from bnetlauncher.ui.game_card import GameCard
from bnetlauncher.ui import hub_pages
from bnetlauncher.ui.sidebar import Sidebar
from bnetlauncher.wine_runner import WineError, WineRunner

_BNET_AGENT_GAME_ID = "_battlenet_agent"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.cfg = get_config()
        self.game_manager = GameManager()
        self.wine_runner = WineRunner()

        self._cards: dict[str, GameCard] = {}
        self._wow_addon_paths: list[Path] = []
        self._selected_game: Game | None = None
        self._hub_home_labels: dict[str, Gtk.Label] = {}
        self._friends_signin_btn: Gtk.Button | None = None

        self._restore_geometry()
        self._build_ui()
        self._connect_signals()

        # Async game library refresh
        self.game_manager.refresh_async(
            callback=lambda: GLib.idle_add(self._reload_games)
        )

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        self.set_default_size(
            self.cfg.get("window_width", 1280),
            self.cfg.get("window_height", 800),
        )
        if self.cfg.get("window_maximized", False):
            self.maximize()

    def _save_geometry(self) -> None:
        if self.is_maximized():
            self.cfg.set("window_maximized", True, autosave=False)
        else:
            w, h = self.get_width(), self.get_height()
            self.cfg.set("window_width", w, autosave=False)
            self.cfg.set("window_height", h, autosave=False)
            self.cfg.set("window_maximized", False, autosave=False)
        self.cfg.save()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outermost box: sidebar + content
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.add_css_class("bnet-root")

        # ── Sidebar ────────────────────────────────────────────────────
        self._sidebar = Sidebar(on_navigate=self._on_navigate)
        root.append(self._sidebar)

        # ── Main stack ─────────────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(180)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)

        self._stack.add_named(self._build_games_view(), "games")
        self._stack.add_named(self._build_home_view(), "home")
        self._stack.add_named(self._build_friends_view(), "friends")
        self._stack.add_named(self._build_shop_view(), "shop")
        self._stack.add_named(self._build_news_view(), "news")
        self._stack.add_named(self._build_settings_stub(), "settings")

        # ── Toast overlay wraps the stack ──────────────────────────────
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._stack)
        self._toast_overlay.set_hexpand(True)
        root.append(self._toast_overlay)

        # ── Header + body + status (ToolbarView since libadwaita 1.4) ──
        header = self._build_headerbar()
        status = self._build_statusbar()
        if hasattr(Adw, "ToolbarView"):
            shell = Adw.ToolbarView()
            shell.add_top_bar(header)
            shell.set_content(root)
            shell.add_bottom_bar(status)
        else:
            shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            shell.append(header)
            root.set_hexpand(True)
            root.set_vexpand(True)
            shell.append(root)
            shell.append(status)

        self.set_content(shell)
        # Select after _stack exists (sidebar construction must not navigate early).
        self._sidebar.select("games")
        self._sync_account_button()

    # -- Header bar ────────────────────────────────────────────────────

    def _build_headerbar(self) -> Adw.HeaderBar:
        hb = Adw.HeaderBar()
        hb.add_css_class("bnet-headerbar")

        # Search entry
        self._search_entry = Gtk.SearchEntry()
        # Gtk ≤4.8: use placeholder-text property; newer has set_placeholder_text().
        if hasattr(self._search_entry, "set_placeholder_text"):
            self._search_entry.set_placeholder_text("Search games…")
        else:
            self._search_entry.set_property("placeholder-text", "Search games…")
        self._search_entry.set_size_request(240, -1)
        self._search_entry.connect("search-changed", self._on_search_changed)
        hb.set_title_widget(self._search_entry)

        # Settings button
        settings_btn = Gtk.Button()
        settings_btn.set_icon_name("preferences-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.add_css_class("flat")
        settings_btn.connect("clicked", self._on_settings_clicked)
        hb.pack_end(settings_btn)

        # Account / login button (Sign In / Sign Out + suggested styling via _sync_account_button)
        self._account_btn = Gtk.Button(label="Sign In")
        self._account_btn.connect("clicked", self._on_account_clicked)
        hb.pack_end(self._account_btn)

        # Refresh button
        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh game library")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        hb.pack_start(refresh_btn)

        return hb

    # -- Status bar ────────────────────────────────────────────────────

    def _build_statusbar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        bar.add_css_class("bnet-status-bar")
        bar.set_margin_start(16)
        bar.set_margin_end(16)

        self._status_label = Gtk.Label(label="Ready")
        self._status_label.add_css_class("bnet-status-label")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)
        bar.append(self._status_label)

        wine_ver = self.wine_runner.get_wine_version()
        wine_label = Gtk.Label(label=wine_ver or "Wine not found")
        wine_label.add_css_class(
            "bnet-status-ok" if wine_ver != "Wine not found" else "bnet-status-error"
        )
        bar.append(wine_label)

        wayland_label = Gtk.Label(label="Wayland ✓" if self._is_wayland() else "XWayland")
        wayland_label.add_css_class("bnet-status-label")
        bar.append(wayland_label)

        return bar

    @staticmethod
    def _is_wayland() -> bool:
        import os
        return bool(os.environ.get("WAYLAND_DISPLAY"))

    # -- Games view ────────────────────────────────────────────────────

    def _build_games_view(self) -> Gtk.Box:
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        container.add_css_class("bnet-content")

        # Left: scrollable game grid
        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        grid_box.add_css_class("bnet-game-grid")

        # Section header
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.set_margin_bottom(20)

        title = Gtk.Label(label="Your Games")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("bnet-section-title")

        subtitle = Gtk.Label(
            label="Wine bottles per game under your prefix dir. Installed titles first."
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("bnet-section-subtitle")

        header.append(title)
        header.append(subtitle)
        grid_box.append(header)

        # FlowBox for responsive card grid
        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_homogeneous(True)
        self._flowbox.set_row_spacing(0)
        self._flowbox.set_column_spacing(0)
        self._flowbox.set_min_children_per_line(2)
        self._flowbox.set_max_children_per_line(6)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flowbox.add_css_class("bnet-game-grid")
        grid_box.append(self._flowbox)

        scroll.set_child(grid_box)
        container.append(scroll)

        # Right: detail panel
        self._detail_panel = self._build_detail_panel()
        container.append(self._detail_panel)

        # Populate cards
        self._populate_game_cards(self.game_manager.get_library_games())

        return container

    def _populate_game_cards(self, games: list[Game]) -> None:
        # Clear existing
        while child := self._flowbox.get_first_child():
            self._flowbox.remove(child)
        self._cards.clear()

        if not games:
            self._selected_game = None
            self._detail_title.set_text("No games in library")
            self._detail_genre.set_text("")
            self._detail_desc.set_text(
                "Enable Settings → Library → Show unsupported titles, or install "
                "a game via the Blizzard desktop app in Wine, then click Refresh."
            )
            self._detail_status.set_text("")
            self._detail_play_btn.set_label("PLAY")
            self._detail_play_btn.set_sensitive(False)
            self._detail_verify_btn.set_sensitive(False)
            self._detail_repair_btn.set_sensitive(True)
            self._clear_wow_addons_ui()
            return

        for game in games:
            card = GameCard(game)
            card.connect_play(self._on_play_clicked)
            card.connect_select(self._on_game_selected)
            self._cards[game.id] = card
            self._flowbox.append(card)

        # Select first installed game
        installed = [g for g in games if g.installed]
        if installed:
            self._select_game(installed[0])
        elif games:
            self._select_game(games[0])

    # -- Detail panel ──────────────────────────────────────────────────

    def _build_detail_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.add_css_class("bnet-detail-panel")
        panel.set_size_request(300, -1)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        inner.set_margin_top(28)
        inner.set_margin_bottom(28)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        # Banner placeholder
        self._detail_banner = Gtk.Box()
        self._detail_banner.set_size_request(-1, 160)
        self._detail_banner.add_css_class("bnet-game-banner")
        inner.append(self._detail_banner)

        self._detail_title = Gtk.Label(label="Select a game")
        self._detail_title.set_halign(Gtk.Align.START)
        self._detail_title.set_wrap(True)
        self._detail_title.add_css_class("bnet-detail-title")
        inner.append(self._detail_title)

        self._detail_genre = Gtk.Label(label="")
        self._detail_genre.set_halign(Gtk.Align.START)
        self._detail_genre.add_css_class("bnet-detail-genre")
        inner.append(self._detail_genre)

        self._detail_desc = Gtk.Label(label="")
        self._detail_desc.set_halign(Gtk.Align.START)
        self._detail_desc.set_wrap(True)
        self._detail_desc.add_css_class("bnet-detail-desc")
        inner.append(self._detail_desc)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._detail_verify_btn = Gtk.Button(label="Verify install")
        self._detail_verify_btn.set_tooltip_text(
            "Check executable and Wine prefix paths for the selected game"
        )
        self._detail_verify_btn.connect("clicked", self._on_verify_install_clicked)
        self._detail_repair_btn = Gtk.Button(label="Repair tips")
        self._detail_repair_btn.set_tooltip_text(
            "Blizzard app Scan and Repair and other troubleshooting"
        )
        self._detail_repair_btn.connect("clicked", self._on_repair_tips_clicked)
        tools.append(self._detail_verify_btn)
        tools.append(self._detail_repair_btn)
        inner.append(tools)

        self._wow_addons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._wow_addons_box.set_visible(False)
        wow_lbl = Gtk.Label(label="WoW add-ons")
        wow_lbl.set_halign(Gtk.Align.START)
        wow_lbl.add_css_class("bnet-card-genre")
        self._wow_addons_box.append(wow_lbl)

        self._wow_listbox = Gtk.ListBox()
        self._wow_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        if hasattr(self._wow_listbox, "set_activate_on_single_click"):
            self._wow_listbox.set_activate_on_single_click(True)
        self._wow_listbox.connect("row-activated", self._on_wow_addon_row_activated)

        pop_scroll = Gtk.ScrolledWindow()
        pop_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        pop_scroll.set_min_content_height(120)
        pop_scroll.set_max_content_height(280)
        pop_scroll.set_child(self._wow_listbox)

        self._wow_addons_popover = Gtk.Popover()
        self._wow_addons_popover.set_child(pop_scroll)

        self._wow_addons_menubtn = Gtk.MenuButton()
        self._wow_addons_menubtn.set_label("Open Add-ons folder…")
        self._wow_addons_menubtn.set_popover(self._wow_addons_popover)
        self._wow_addons_menubtn.set_halign(Gtk.Align.START)
        self._wow_addons_box.append(self._wow_addons_menubtn)
        inner.append(self._wow_addons_box)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        inner.append(spacer)

        self._detail_status = Gtk.Label(label="")
        self._detail_status.set_halign(Gtk.Align.START)
        self._detail_status.add_css_class("bnet-card-genre")
        inner.append(self._detail_status)

        self._detail_play_btn = Gtk.Button(label="PLAY")
        self._detail_play_btn.add_css_class("bnet-detail-play-btn")
        self._detail_play_btn.connect("clicked", self._on_detail_play_clicked)
        inner.append(self._detail_play_btn)

        panel.append(inner)
        return panel

    def _select_game(self, game: Game) -> None:
        self._selected_game = game
        self._detail_title.set_text(game.name)
        self._detail_genre.set_text(game.genre.upper())
        self._detail_verify_btn.set_sensitive(True)
        self._detail_repair_btn.set_sensitive(True)

        if not game.linux_supported:
            reason = (game.unsupported_reason or "Marked unsupported on Linux/Wine.").strip()
            self._detail_desc.set_text(game.description + "\n\n" + reason)
            self._detail_status.set_text("Unsupported on Linux/Wine")
            self._detail_play_btn.set_label("UNSUPPORTED")
            self._detail_play_btn.set_sensitive(False)
            self._clear_wow_addons_ui()
            return

        if game.installed:
            self._detail_desc.set_text(game.description)
            self._detail_status.set_text("Installed")
            self._detail_play_btn.set_label("PLAY")
            self._detail_play_btn.set_sensitive(not self.wine_runner.is_running(game.id))
        else:
            tip = (
                "\n\nTip: Blizzard's page usually downloads Battle.net-Setup.exe first. "
                "Run it with Wine, install the game inside Battle.net, then Refresh."
            )
            self._detail_desc.set_text(game.description + tip)
            self._detail_status.set_text("Not installed")
            self._detail_play_btn.set_label("INSTALL")
            self._detail_play_btn.set_sensitive(True)

        self._sync_wow_addons_ui(game)

    # -- Hub pages (Home / Friends / Shop / News) ─────────────────────

    def _build_home_view(self) -> Gtk.Widget:
        page, labels = hub_pages.build_home_page(
            on_browse_games=self._go_to_games,
            on_refresh=lambda: self._on_refresh_clicked(None),
        )
        self._hub_home_labels = labels
        self._update_home_stats()
        return page

    def _build_friends_view(self) -> Gtk.Widget:
        page, sign_btn = hub_pages.build_friends_page(
            on_sign_in=lambda: self._on_account_clicked(None),
            on_open_url=self._open_external_url,
        )
        self._friends_signin_btn = sign_btn
        self._refresh_friends_signin_button()
        return page

    def _build_shop_view(self) -> Gtk.Widget:
        return hub_pages.build_shop_page(self._open_external_url)

    def _build_news_view(self) -> Gtk.Widget:
        return hub_pages.build_news_page(self._open_external_url)

    def _go_to_games(self) -> None:
        self._stack.set_visible_child_name("games")
        self._sidebar.select("games")

    def _open_external_url(self, url: str) -> None:
        if not open_default_browser(url):
            self._toast("Could not open a web browser for this link.", is_error=True)

    def _update_home_stats(self) -> None:
        if not self._hub_home_labels:
            return
        games = self.game_manager.get_library_games()
        n_inst = sum(1 for g in games if g.installed)
        self._hub_home_labels["installed"].set_text(str(n_inst))
        self._hub_home_labels["total"].set_text(str(len(games)))
        wv = self.wine_runner.get_wine_version()
        self._hub_home_labels["wine"].set_text(
            wv if wv != "Wine not found" else "Not found"
        )
        auth = BNetAuth()
        if auth.has_stored_token():
            acct = (
                "Signed in"
                if auth.is_authenticated()
                else "Signed in (session expired — use Sign Out and sign in again)"
            )
        else:
            acct = "Not signed in"
        self._hub_home_labels["account"].set_text(acct)

    def _refresh_friends_signin_button(self) -> None:
        btn = self._friends_signin_btn
        if not btn:
            return
        auth = BNetAuth()
        if auth.has_stored_token():
            btn.set_label("Signed in (friend list API not wired yet)")
            btn.set_sensitive(False)
        else:
            btn.set_label("Sign in (Blizzard OAuth)")
            btn.set_sensitive(True)

    def _sync_hub_page(self, view_id: str) -> None:
        if view_id == "home":
            self._update_home_stats()
        elif view_id == "friends":
            self._refresh_friends_signin_button()

    # -- Settings stub (sidebar) ─────────────────────────────────────

    def _build_settings_stub(self) -> Adw.StatusPage:
        page = Adw.StatusPage()
        page.set_icon_name("preferences-system-symbolic")
        page.set_title("Settings")
        page.set_description("Open Settings from the toolbar button above.")
        return page

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_navigate(self, view_id: str) -> None:
        self._stack.set_visible_child_name(view_id)
        self._search_entry.set_visible(view_id == "games")
        self._sync_hub_page(view_id)
        if view_id == "settings":
            GLib.idle_add(self._open_settings_dialog)

    def _on_game_selected(self, game: Game) -> None:
        self._select_game(game)

    def _on_play_clicked(self, game: Game) -> None:
        self._launch_game(game)

    def _on_detail_play_clicked(self, _) -> None:
        if self._selected_game:
            self._launch_game(self._selected_game)

    def _on_verify_install_clicked(self, _) -> None:
        g = self._selected_game
        if not g:
            return
        ok, issues = install_health.verify_install(g, self.wine_runner)
        if ok:
            self._toast(f"{g.name}: install paths look OK.")
        else:
            self._toast(f"{g.name}: " + " ".join(issues), is_error=True)

    def _on_repair_tips_clicked(self, _) -> None:
        self._toast(install_health.repair_instructions_text())

    def _clear_wow_addons_ui(self) -> None:
        self._wow_addons_box.set_visible(False)
        while child := self._wow_listbox.get_first_child():
            self._wow_listbox.remove(child)
        self._wow_addon_paths.clear()

    def _sync_wow_addons_ui(self, game: Game) -> None:
        self._clear_wow_addons_ui()
        if game.id != "wow" or not game.installed or not game.linux_supported:
            return
        path = (game.install_path or "").strip()
        if not path:
            return
        targets = wow_addons.enumerate_addon_folders(Path(path))
        if not targets:
            return
        self._wow_addon_paths = [p for _, p in targets]
        for label, _ in targets:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=label, xalign=0)
            lbl.set_margin_start(12)
            lbl.set_margin_end(12)
            lbl.set_margin_top(10)
            lbl.set_margin_bottom(10)
            row.set_child(lbl)
            self._wow_listbox.append(row)
        self._wow_addons_box.set_visible(True)

    def _on_wow_addon_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if idx < 0 or idx >= len(self._wow_addon_paths):
            return
        addons = self._wow_addon_paths[idx]
        ok, err = wow_addons.ensure_and_open_addons(addons)
        self._wow_addons_popover.popdown()
        if ok:
            self._toast(f"Opened add-ons folder ({addons.name}).")
        else:
            self._toast(f"Could not open add-ons folder: {err}", is_error=True)

    def _launch_game(self, game: Game) -> None:
        if not game.linux_supported:
            self._toast(
                game.unsupported_reason or "This title is not supported on Linux/Wine.",
                is_error=True,
            )
            return
        if not game.installed:
            self._start_install(game)
            return

        if self.wine_runner.is_running(game.id):
            self._toast(f"{game.name} is already running.")
            return

        # Update UI
        if card := self._cards.get(game.id):
            card.set_playing(True)
        self._detail_play_btn.set_sensitive(False)
        self._set_status(f"Launching {game.name}…")

        try:
            self.wine_runner.launch(
                game_id=game.id,
                executable=game.install_path,
                on_exit=lambda rc: GLib.idle_add(self._on_game_exited, game.id, rc),
            )
            self.game_manager.update_last_played(game.id)
            self._set_status(f"{game.name} is running")
        except WineError as e:
            self._toast(f"Launch failed: {e}", is_error=True)
            if card := self._cards.get(game.id):
                card.set_playing(False)
            self._detail_play_btn.set_sensitive(True)
            self._set_status("Launch failed")

    def _start_install(self, game: Game) -> None:
        """Open Blizzard download page and start the desktop agent .exe in Wine when found."""
        if not game.linux_supported:
            self._toast(
                game.unsupported_reason or "This title is not supported on Linux/Wine.",
                is_error=True,
            )
            return
        url = self.game_manager.install_download_url(game.id)
        browser_ok = open_default_browser(url)
        if not browser_ok:
            print(
                "bnetlauncher: could not open a browser; open this URL manually:\n"
                f"  {url}\n",
                file=sys.stderr,
                flush=True,
            )
            print_browser_open_hints()

        bnet_exe = self.wine_runner.find_battle_net_executable()
        if bnet_exe:
            if self.wine_runner.is_running(_BNET_AGENT_GAME_ID):
                if browser_ok:
                    self._toast(
                        f"The Blizzard desktop app is already running. Install {game.name} there, "
                        "then click refresh."
                    )
                else:
                    self._toast(
                        "Blizzard desktop app is already running. Install the game there, then refresh."
                    )
                self._set_status("Use the Blizzard app to install, then refresh the library")
                return
            prefix = self.wine_runner.wine_prefix_for_exe(bnet_exe)
            if not prefix:
                if browser_ok:
                    self._toast(
                        f"Opened install page for {game.name}. "
                        "Could not detect Wine prefix for the Blizzard app. Install via browser."
                    )
                else:
                    self._toast(
                        "Could not open browser or detect the Blizzard app prefix. "
                        "Install from download.battle.net, then refresh.",
                        is_error=True,
                    )
                return
            try:
                self.wine_runner.launch(
                    game_id=_BNET_AGENT_GAME_ID,
                    executable=bnet_exe,
                    prefix=prefix,
                    on_exit=lambda rc: GLib.idle_add(
                        self._on_bnet_agent_exited, rc
                    ),
                )
                if browser_ok:
                    self._toast(
                        f"Opened the Blizzard desktop app and the page for {game.name}. "
                        "Install in the app, then refresh."
                    )
                else:
                    self._toast(
                        f"Started the Blizzard desktop app. Install {game.name}, then refresh."
                    )
                self._set_status("Blizzard app running. After install, click refresh")
            except WineError as e:
                msg = f"Could not start the Blizzard desktop app: {e}"
                if browser_ok:
                    msg += " The download page may still be open in your browser."
                self._toast(msg, is_error=True)
        elif browser_ok:
            self._toast(
                f"Opened Blizzard's page for {game.name}. "
                "It usually downloads Battle.net-Setup.exe. Run that with Wine, "
                "then install the game inside Battle.net and click refresh."
            )
            self._set_status("Run Battle.net-Setup.exe in Wine, then refresh")
        else:
            self._toast(
                "Could not open a browser. Install the Blizzard desktop app from "
                "https://download.battle.net then refresh the library.",
                is_error=True,
            )
            self._set_status("Install the Blizzard desktop app manually, then refresh")

    def _on_bnet_agent_exited(self, returncode: int) -> None:
        self._set_status(
            "Ready" if returncode == 0 else f"Blizzard desktop app exited with code {returncode}"
        )

    def _on_game_exited(self, game_id: str, returncode: int) -> None:
        if card := self._cards.get(game_id):
            card.set_playing(False)
        if self._selected_game and self._selected_game.id == game_id:
            self._detail_play_btn.set_sensitive(True)
        self._set_status(
            "Ready" if returncode == 0 else f"Game exited with code {returncode}"
        )

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().lower().strip()
        games = self.game_manager.get_library_games()
        if query:
            games = [g for g in games if query in g.name.lower() or query in g.genre.lower()]
        self._populate_game_cards(games)

    def _on_refresh_clicked(self, _) -> None:
        self._set_status("Scanning game library…")
        self.game_manager.refresh_async(
            callback=lambda: GLib.idle_add(self._reload_games)
        )

    def _on_account_clicked(self, _) -> None:
        auth = BNetAuth()
        if auth.has_stored_token():
            auth.clear_tokens()
            self._sync_account_button()
            self._toast("Signed out. Tokens cleared on this device.")
            self._refresh_friends_signin_button()
            self._update_home_stats()
            return
        self._account_btn.set_sensitive(False)
        self._account_btn.set_label("Signing in…")
        auth.start_auth_flow(
            on_success=lambda token: GLib.idle_add(self._on_auth_success, token),
            on_error=lambda msg: GLib.idle_add(self._on_auth_error, msg),
        )

    def _on_auth_success(self, token: str) -> None:
        self._account_btn.set_sensitive(True)
        self._sync_account_button()
        self._toast("Signed in successfully!")
        self._refresh_friends_signin_button()
        self._update_home_stats()

    def _on_auth_error(self, msg: str) -> None:
        self._account_btn.set_sensitive(True)
        self._sync_account_button()
        self._toast(f"Sign-in failed: {msg}", is_error=True)
        self._refresh_friends_signin_button()
        self._update_home_stats()

    def _on_settings_clicked(self, _) -> None:
        self._open_settings_dialog()

    def _on_close(self, _) -> bool:
        self._save_geometry()
        return False  # allow close

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sync_account_button(self) -> None:
        """Header label reflects stored OAuth token (Sign Out if any token on disk)."""
        auth = BNetAuth()
        signed_in = auth.has_stored_token()
        self._account_btn.set_sensitive(True)
        if signed_in:
            tip = "Click to clear Blizzard OAuth tokens on this device."
            if not auth.is_authenticated():
                tip = (
                    "Token saved but session expired or clock skew. "
                    "Sign out and sign in again, or check the system clock. " + tip
                )
            self._account_btn.set_label("Sign Out")
            self._account_btn.set_tooltip_text(tip)
            self._account_btn.remove_css_class("suggested-action")
        else:
            self._account_btn.set_label("Sign In")
            self._account_btn.set_tooltip_text("Sign in with Blizzard (OAuth)")
            self._account_btn.add_css_class("suggested-action")

    def _reload_games(self) -> None:
        self._populate_game_cards(self.game_manager.get_library_games())
        installed_count = sum(1 for g in self.game_manager.get_all() if g.installed)
        self._set_status(f"Library refreshed. {installed_count} game(s) installed.")
        self._update_home_stats()

    def _set_status(self, msg: str) -> None:
        self._status_label.set_text(msg)

    def _toast(self, message: str, is_error: bool = False) -> None:
        # Adw.Toast title is Pango markup. Newlines break parsing across "lines" with raw
        # URLs; collapse whitespace, then escape &, <, >.
        text = " ".join((message or "").split())
        safe_title = GLib.markup_escape_text(text, -1)
        toast = Adw.Toast(title=safe_title)
        toast.set_timeout(12 if len(text) > 120 else 4)
        self._toast_overlay.add_toast(toast)

    def _open_settings_dialog(self) -> None:
        from bnetlauncher.ui.settings import SettingsDialog

        def _on_library_prefs_changed() -> None:
            # Rescan disk (custom paths, etc.) then refresh the grid.
            self.game_manager.refresh_async(
                callback=lambda: GLib.idle_add(self._reload_games),
            )

        SettingsDialog(
            parent=self,
            on_library_prefs_changed=_on_library_prefs_changed,
        )
        # Switch back to games view
        self._stack.set_visible_child_name("games")
        self._sidebar.select("games")
