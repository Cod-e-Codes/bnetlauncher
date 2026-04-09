"""Unit tests for WoW add-on path helpers (no GTK)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bnetlauncher import wow_addons


class TestFlavorLabel(unittest.TestCase):
    def test_known(self) -> None:
        self.assertEqual(wow_addons.flavor_label("_retail_"), "Retail")
        self.assertEqual(wow_addons.flavor_label("_classic_"), "Classic")

    def test_unknown(self) -> None:
        self.assertEqual(wow_addons.flavor_label("_foo_bar_"), "Foo Bar")


class TestWowInstallRoot(unittest.TestCase):
    def test_retail_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            retail = root / "_retail_"
            retail.mkdir(parents=True)
            exe = retail / "Wow.exe"
            exe.write_bytes(b"")
            self.assertEqual(wow_addons.wow_install_root(exe), root.resolve())

    def test_classic_exe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            classic = root / "_classic_"
            classic.mkdir(parents=True)
            exe = classic / "WowClassic.exe"
            exe.write_bytes(b"")
            self.assertEqual(wow_addons.wow_install_root(exe), root.resolve())

    def test_missing_file(self) -> None:
        p = Path("/nonexistent/wow/Wow.exe")
        self.assertIsNone(wow_addons.wow_install_root(p))

    def test_wrong_exe_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "notwow.exe"
            p.write_bytes(b"")
            self.assertIsNone(wow_addons.wow_install_root(p))


class TestEnumerateAddonFolders(unittest.TestCase):
    def test_multiple_flavors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            r = root / "_retail_"
            c = root / "_classic_"
            r.mkdir(parents=True)
            c.mkdir(parents=True)
            (r / "Wow.exe").write_bytes(b"")
            (c / "WowClassic.exe").write_bytes(b"")
            exe = r / "Wow.exe"
            pairs = wow_addons.enumerate_addon_folders(exe)
            labels = {a[0] for a in pairs}
            paths = {a[1] for a in pairs}
            self.assertIn("Retail", labels)
            self.assertIn("Classic", labels)
            self.assertIn(r / "Interface" / "AddOns", paths)
            self.assertIn(c / "Interface" / "AddOns", paths)

    def test_skips_non_underscore_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            retail = root / "_retail_"
            junk = root / "Data"
            retail.mkdir(parents=True)
            junk.mkdir(parents=True)
            (retail / "Wow.exe").write_bytes(b"")
            pairs = wow_addons.enumerate_addon_folders(retail / "Wow.exe")
            self.assertEqual(len(pairs), 1)

    def test_invalid_exe_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.exe"
            p.write_bytes(b"")
            self.assertEqual(wow_addons.enumerate_addon_folders(p), [])


class TestEnsureAndVerify(unittest.TestCase):
    def test_ensure_creates_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            addons = Path(td) / "a" / "Interface" / "AddOns"
            ok, err = wow_addons.ensure_addons_directory(addons)
            self.assertTrue(ok)
            self.assertEqual(err, "")
            self.assertTrue(addons.is_dir())

    @mock.patch("bnetlauncher.wow_addons.which")
    @mock.patch("bnetlauncher.wow_addons.subprocess.Popen")
    def test_open_directory_uses_xdg_open(self, popen: mock.MagicMock, which: mock.MagicMock) -> None:
        which.return_value = "/usr/bin/xdg-open"
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ok, err = wow_addons.open_directory_in_file_manager(d)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], "/usr/bin/xdg-open")

    def test_verify_ok_when_addons_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            retail = root / "_retail_"
            retail.mkdir(parents=True)
            (retail / "Wow.exe").write_bytes(b"")
            exe = retail / "Wow.exe"
            ok, issues = wow_addons.verify_wow_addon_layout(exe)
            self.assertTrue(ok)
            self.assertEqual(issues, [])

    def test_verify_fails_if_interface_is_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "World of Warcraft"
            retail = root / "_retail_"
            retail.mkdir(parents=True)
            (retail / "Wow.exe").write_bytes(b"")
            iface = retail / "Interface"
            iface.write_bytes(b"bad")
            exe = retail / "Wow.exe"
            ok, issues = wow_addons.verify_wow_addon_layout(exe)
            self.assertFalse(ok)
            self.assertTrue(any("not a directory" in m for m in issues))


class TestInstallHealthWow(unittest.TestCase):
    def test_verify_includes_wow_for_wow_id(self) -> None:
        from bnetlauncher.game_manager import Game
        from bnetlauncher.install_health import verify_install
        from bnetlauncher.wine_runner import WineRunner

        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "pfx"
            drive_c = prefix / "drive_c"
            wow_root = drive_c / "Program Files" / "World of Warcraft"
            retail = wow_root / "_retail_"
            retail.mkdir(parents=True)
            exe = retail / "Wow.exe"
            exe.write_bytes(b"")

            game = Game(
                id="wow",
                name="World of Warcraft",
                slug="wow",
                install_path=str(exe),
                installed=True,
                genre="MMORPG",
                description="",
                background_color="#000",
                icon="wow",
                linux_supported=True,
                unsupported_reason="",
            )
            runner = WineRunner()
            ok, issues = verify_install(game, runner)
            self.assertTrue(ok, issues)


if __name__ == "__main__":
    unittest.main()
