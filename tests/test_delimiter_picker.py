# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Tests for the shared Split/Join delimiter picker."""

from __future__ import annotations

from pathlib import Path


def test_delimiter_picker_enables_custom_only_for_custom_mode(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.delimiter_picker import DelimiterPicker

    picker = DelimiterPicker(
        (("Comma (,)", "comma"), ("Custom", "custom")),
        combo_tooltip="tooltip",
        custom_placeholder=r"\t",
        custom_tooltip="custom",
        custom_max_length=8,
    )
    assert picker.mode() == "comma"
    assert picker.custom_input.isEnabled() is False
    seen: list[str] = []
    picker.connect_changed(lambda: seen.append(picker.mode()))
    picker.combo.setCurrentIndex(1)
    assert picker.mode() == "custom"
    assert picker.custom_input.isEnabled() is True
    assert seen == ["custom"]
    picker.combo.setCurrentIndex(0)
    assert picker.custom_input.isEnabled() is False
    assert seen == ["custom", "comma"]


def test_split_and_join_dialogs_use_shared_picker() -> None:
    root = Path(__file__).resolve().parents[1] / "molmanager" / "ui" / "dialogs"
    for name in ("split_column.py", "join_columns.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from .delimiter_picker import DelimiterPicker" in text
        assert "def _sync_custom_enabled" not in text
