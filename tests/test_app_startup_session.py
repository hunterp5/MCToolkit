# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Startup ``--load-session`` overlay + deferred apply."""

from __future__ import annotations


def test_startup_load_session_shows_overlay_before_window_and_defers(qapp, monkeypatch):  # noqa: ARG001
    from mctoolkit import app as app_mod

    events: list[object] = []
    deferred: list = []

    class FakeWin:
        def __init__(self):
            events.append("construct")

        def _show_session_open_overlay(self) -> None:
            events.append("overlay")

        def show(self) -> None:
            events.append("show")

        def apply_saved_session_from_file(self, path: str) -> bool:
            events.append(("apply", path))
            return True

    class FakeApp:
        def __init__(self, *_a, **_k):
            pass

        def setAttribute(self, *_a, **_k) -> None:  # noqa: N802 — Qt API
            pass

        def exec(self) -> int:
            for fn in list(deferred):
                fn()
            return 0

    monkeypatch.setattr(app_mod, "ChemistryWorkspaceWindow", FakeWin)
    monkeypatch.setattr(app_mod, "QApplication", FakeApp)
    monkeypatch.setattr(app_mod, "hide_owned_windows_console", lambda: None)
    monkeypatch.setattr(app_mod, "_configure_logging", lambda: None)
    monkeypatch.setattr(app_mod, "configure_rdkit_for_desktop_app", lambda: None)
    monkeypatch.setattr(app_mod, "_preload_qt_webengine", lambda: None)
    monkeypatch.setattr(app_mod, "apply_qt_application_identity", lambda *_a, **_k: None)
    monkeypatch.setattr(app_mod, "bootstrap_application_gui", lambda *_a, **_k: None)
    monkeypatch.setattr(app_mod, "is_session_document_path", lambda _p: True)
    monkeypatch.setattr(
        "mctoolkit.platform_support.qt_windows_caption.apply_classic_native_captions",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        app_mod.QTimer,
        "singleShot",
        lambda _ms, fn: deferred.append(fn),
    )

    code = app_mod.main(["mctoolkit", "--load-session", "C:/tmp/demo.mct"])
    assert code == 0
    assert events[:3] == ["construct", "overlay", "show"]
    assert ("apply", "C:/tmp/demo.mct") in events
    assert events.index("overlay") < events.index("show")
    assert events.index("show") < events.index(("apply", "C:/tmp/demo.mct"))
