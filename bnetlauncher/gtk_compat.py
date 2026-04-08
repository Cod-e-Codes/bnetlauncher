"""GTK introspection differences across distro versions (e.g. Ubuntu 22.04 vs 24.04)."""
from __future__ import annotations

from gi.repository import Gtk


def css_provider_load_string(provider: Gtk.CssProvider, css: str) -> None:
    """Load CSS text; prefers Gtk 4.12+ load_from_string, falls back to load_from_data."""
    load_str = getattr(provider, "load_from_string", None)
    if load_str is not None:
        load_str(css)
    else:
        provider.load_from_data(css.encode("utf-8"))
