"""
Home, Friends, Shop, and News stack pages (non-games hub UI).
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from typing import Callable


def _scroll(inner: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow()
    sw.set_hexpand(True)
    sw.set_vexpand(True)
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_child(inner)
    return sw


def _section_title(text: str) -> Gtk.Label:
    lb = Gtk.Label(label=text)
    lb.set_halign(Gtk.Align.START)
    lb.add_css_class("bnet-section-title")
    return lb


def _body(text: str) -> Gtk.Label:
    lb = Gtk.Label(label=text)
    lb.set_halign(Gtk.Align.START)
    lb.set_wrap(True)
    lb.set_xalign(0)
    lb.add_css_class("bnet-hub-body")
    return lb


def _pill_button(label: str, css: str = "bnet-hub-button") -> Gtk.Button:
    b = Gtk.Button(label=label)
    b.add_css_class(css)
    # GTK's CSS engine (e.g. 4.6) does not support flex properties like justify-content;
    # align label start for full-width link rows.
    if css == "bnet-hub-link-row":
        b.set_halign(Gtk.Align.FILL)
        child = b.get_first_child()
        if isinstance(child, Gtk.Label):
            child.set_halign(Gtk.Align.START)
            child.set_xalign(0)
    return b


def _stat_box(title: str, value_label: Gtk.Label) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("bnet-home-stat")
    box.set_size_request(140, -1)

    t = Gtk.Label(label=title)
    t.add_css_class("bnet-home-stat-title")
    t.set_halign(Gtk.Align.START)

    value_label.set_halign(Gtk.Align.START)
    value_label.add_css_class("bnet-home-stat-value")

    box.append(t)
    box.append(value_label)
    return box


def build_home_page(
    on_browse_games: Callable[[], None],
    on_refresh: Callable[[], None],
) -> tuple[Gtk.Widget, dict[str, Gtk.Label]]:
    """Returns scrolled page and labels keyed: installed, total, wine, account."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    outer.set_margin_start(40)
    outer.set_margin_end(40)
    outer.set_margin_top(36)
    outer.set_margin_bottom(36)

    outer.append(_section_title("Welcome"))
    outer.append(
        _body(
            "Independent GTK launcher for Blizzard titles on Linux: per-game Wine "
            "prefixes, Wayland-safe launches, and browser links for installs and "
            "news. Not affiliated with Blizzard."
        )
    )

    stats_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    stats_row.set_margin_top(8)

    li = Gtk.Label(label="-")
    lt = Gtk.Label(label="-")
    lw = Gtk.Label(label="-")
    la = Gtk.Label(label="-")

    stats_row.append(_stat_box("Installed", li))
    stats_row.append(_stat_box("In library", lt))
    stats_row.append(_stat_box("Wine", lw))
    stats_row.append(_stat_box("Account", la))
    outer.append(stats_row)

    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    btn_row.set_margin_top(12)

    b1 = _pill_button("Browse games")
    b1.connect("clicked", lambda *_: on_browse_games())
    b2 = _pill_button("Refresh library", "bnet-hub-button-secondary")
    b2.connect("clicked", lambda *_: on_refresh())

    btn_row.append(b1)
    btn_row.append(b2)
    outer.append(btn_row)

    return _scroll(outer), {
        "installed": li,
        "total": lt,
        "wine": lw,
        "account": la,
    }


def build_friends_page(
    on_sign_in: Callable[[], None],
    on_open_url: Callable[[str], None],
) -> tuple[Gtk.Widget, Gtk.Button]:
    """Returns scrolled page and Sign in button (toggle sensitive when authed)."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    outer.set_margin_start(40)
    outer.set_margin_end(40)
    outer.set_margin_top(36)
    outer.set_margin_bottom(36)

    outer.append(_section_title("Friends"))
    outer.append(
        _body(
            "Friend lists and presence use Blizzard's network. This app does not yet "
            "call Blizzard social APIs; sign in below or open the official site in "
            "your browser."
        )
    )

    sign_btn = _pill_button("Sign in (Blizzard OAuth)")
    sign_btn.connect("clicked", lambda *_: on_sign_in())
    outer.append(sign_btn)

    social = _pill_button("Open Blizzard site (social & chat)", "bnet-hub-button-secondary")
    social.connect(
        "clicked",
        lambda *_: on_open_url("https://battle.net/"),
    )
    outer.append(social)

    return _scroll(outer), sign_btn


def build_shop_page(on_open_url: Callable[[str], None]) -> Gtk.Widget:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    outer.set_margin_start(40)
    outer.set_margin_end(40)
    outer.set_margin_top(36)
    outer.set_margin_bottom(36)

    outer.append(_section_title("Shop"))
    outer.append(
        _body("Open the official Blizzard storefront and account services in your browser.")
    )

    links = [
        ("Blizzard shop (web)", "https://shop.battle.net/en-us"),
        ("WoW subscriptions & services", "https://shop.battle.net/en-us/family/world-of-warcraft"),
        ("Diablo IV", "https://shop.battle.net/en-us/family/diablo"),
        ("Overwatch coins & bundles", "https://shop.battle.net/en-us/family/overwatch"),
        ("Hearthstone", "https://shop.battle.net/en-us/family/hearthstone"),
    ]

    for title, url in links:
        b = _pill_button(title, "bnet-hub-link-row")

        def _handler(u: str) -> Callable[[Gtk.Button], None]:
            def _clicked(_btn: Gtk.Button) -> None:
                on_open_url(u)

            return _clicked

        b.connect("clicked", _handler(url))
        outer.append(b)

    return _scroll(outer)


def build_news_page(on_open_url: Callable[[str], None]) -> Gtk.Widget:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    outer.set_margin_start(40)
    outer.set_margin_end(40)
    outer.set_margin_top(36)
    outer.set_margin_bottom(36)

    outer.append(_section_title("News"))
    outer.append(
        _body("Official news and community hubs open in your default browser (WSL uses Windows when needed).")
    )

    links = [
        ("Blizzard News (all games)", "https://news.blizzard.com/en-us"),
        ("World of Warcraft", "https://news.blizzard.com/en-us/world-of-warcraft"),
        ("Diablo", "https://news.blizzard.com/en-us/diablo4"),
        ("Overwatch 2", "https://news.blizzard.com/en-us/overwatch"),
        ("Community forums", "https://us.forums.blizzard.com/en/blizzard/categories"),
    ]

    for title, url in links:
        b = _pill_button(title, "bnet-hub-link-row")

        def _handler(u: str) -> Callable[[Gtk.Button], None]:
            def _clicked(_btn: Gtk.Button) -> None:
                on_open_url(u)

            return _clicked

        b.connect("clicked", _handler(url))
        outer.append(b)

    return _scroll(outer)
