"""
Sidebar navigation panel.
"""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class SidebarItem:
    def __init__(self, label: str, icon: str, view_id: str) -> None:
        self.label = label
        self.icon = icon
        self.view_id = view_id


SIDEBAR_ITEMS = [
    SidebarItem("Home",       "go-home-symbolic",              "home"),
    SidebarItem("Games",      "applications-games-symbolic",   "games"),
    SidebarItem("Friends",    "system-users-symbolic",         "friends"),
    SidebarItem("Shop",       "web-browser-symbolic",          "shop"),
    SidebarItem("News",       "help-contents-symbolic",        "news"),
]

SIDEBAR_BOTTOM = [
    SidebarItem("Settings",  "preferences-system-symbolic",   "settings"),
]


class Sidebar(Gtk.Box):
    """
    Vertical sidebar with navigation buttons.
    Calls on_navigate(view_id) when an item is pressed.
    """

    def __init__(self, on_navigate) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_navigate = on_navigate
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._current: str | None = None
        self.add_css_class("bnet-sidebar")
        self.set_size_request(220, -1)
        self._build()

    def _build(self) -> None:
        # ── Logo / brand area ──────────────────────────────────────────
        logo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        logo_box.set_margin_top(20)
        logo_box.set_margin_bottom(28)
        logo_box.set_margin_start(20)
        logo_box.set_margin_end(20)

        logo_icon = Gtk.Image.new_from_icon_name("applications-games")
        logo_icon.set_pixel_size(32)
        logo_icon.add_css_class("bnet-logo-icon")

        logo_label = Gtk.Label(label="bnetlauncher")
        logo_label.add_css_class("bnet-logo-label")

        logo_box.append(logo_icon)
        logo_box.append(logo_label)
        self.append(logo_box)

        # ── Navigation items ───────────────────────────────────────────
        for item in SIDEBAR_ITEMS:
            btn = self._make_nav_btn(item)
            self.append(btn)

        # Spacer pushes bottom items down
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.append(spacer)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        separator.add_css_class("bnet-sidebar-sep")
        self.append(separator)

        for item in SIDEBAR_BOTTOM:
            btn = self._make_nav_btn(item)
            self.append(btn)

        # ── Version label ──────────────────────────────────────────────
        ver = Gtk.Label(label="v1.0.0")
        ver.add_css_class("bnet-version-label")
        ver.set_margin_bottom(12)
        self.append(ver)

    def _make_nav_btn(self, item: SidebarItem) -> Gtk.ToggleButton:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(2)
        box.set_margin_bottom(2)

        icon = Gtk.Image.new_from_icon_name(item.icon)
        icon.set_pixel_size(18)
        icon.add_css_class("bnet-nav-icon")

        label = Gtk.Label(label=item.label)
        label.set_halign(Gtk.Align.START)
        label.add_css_class("bnet-nav-label")

        box.append(icon)
        box.append(label)

        btn = Gtk.ToggleButton()
        btn.set_child(box)
        btn.add_css_class("bnet-nav-btn")
        btn.set_can_focus(True)

        btn.connect("toggled", self._on_toggled, item.view_id)
        self._buttons[item.view_id] = btn
        return btn

    def _on_toggled(self, btn: Gtk.ToggleButton, view_id: str) -> None:
        if not btn.get_active():
            return  # don't fire on deactivation

        # Deactivate others
        for vid, b in self._buttons.items():
            if vid != view_id and b.get_active():
                b.handler_block_by_func(self._on_toggled)
                b.set_active(False)
                b.handler_unblock_by_func(self._on_toggled)

        self._current = view_id
        self._on_navigate(view_id)

    def select(self, view_id: str) -> None:
        btn = self._buttons.get(view_id)
        if btn and not btn.get_active():
            btn.set_active(True)
