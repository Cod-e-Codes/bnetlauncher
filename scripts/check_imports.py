#!/usr/bin/env python3
"""Smoke-test imports (Linux GTK stack). Run: python3 scripts/check_imports.py"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from bnetlauncher.app import BNetApplication  # noqa: E402
from bnetlauncher.main import setup_environment  # noqa: E402

setup_environment()
print("imports_ok", Gtk, Adw, BNetApplication)
