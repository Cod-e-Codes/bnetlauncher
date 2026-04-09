"""Unit tests for Wine/Proton resolution helpers."""
from __future__ import annotations

import unittest
from unittest import mock

from bnetlauncher.wine_runner import WineRunner


class TestWineResolution(unittest.TestCase):
    def test_resolve_wine_uses_system_when_proton_disabled(self) -> None:
        runner = WineRunner()
        with mock.patch.object(runner, "_resolve_system_wine", return_value="/usr/bin/wine64") as sys_wine:
            with mock.patch.object(runner, "_resolve_proton") as proton:
                runner.cfg.set("use_proton", False)
                got = runner._resolve_wine()
        self.assertEqual(got, "/usr/bin/wine64")
        sys_wine.assert_called_once()
        proton.assert_not_called()

    def test_resolve_wine_uses_proton_when_enabled(self) -> None:
        runner = WineRunner()
        with mock.patch.object(runner, "_resolve_proton", return_value="/steam/Proton/proton") as proton:
            with mock.patch.object(runner, "_resolve_system_wine") as sys_wine:
                runner.cfg.set("use_proton", True)
                got = runner._resolve_wine()
        self.assertEqual(got, "/steam/Proton/proton")
        proton.assert_called_once()
        sys_wine.assert_not_called()

    def test_proton_fallback_calls_system_wine_once(self) -> None:
        runner = WineRunner()
        runner.cfg.set("proton_path", "")
        with mock.patch("bnetlauncher.wine_runner.Path.is_dir", return_value=False):
            with mock.patch.object(runner, "_resolve_system_wine", return_value="/usr/bin/wine64") as sys_wine:
                got = runner._resolve_proton()
        self.assertEqual(got, "/usr/bin/wine64")
        sys_wine.assert_called_once()


if __name__ == "__main__":
    unittest.main()
