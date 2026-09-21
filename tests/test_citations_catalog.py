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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for Help → Citations catalog and dialog."""

from __future__ import annotations

from mctoolkit.reference.citations_catalog import (
    CITATION_SECTIONS,
    iter_tool_citations,
    tool_citation,
    tool_citation_html_fragment,
)
from mctoolkit.ui.citations_dialog import citation_html, open_citations_dialog
from mctoolkit.ui.hotkeys import default_shortcuts


def test_catalog_ids_unique_and_licensed() -> None:
    tools = iter_tool_citations()
    ids = [t.tool_id for t in tools]
    assert len(ids) == len(set(ids))
    assert sum(len(s.tools) for s in CITATION_SECTIONS) == len(tools)
    assert len(tools) >= 20
    for tool in tools:
        assert tool.name.strip()
        assert tool.used_in.strip()
        assert tool.license_name.strip()
        assert tool.license_url.startswith("https://")


def test_catalog_includes_key_dois() -> None:
    html_all = " ".join(tool_citation_html_fragment(t) for t in iter_tool_citations())
    for doi in (
        "10.1021/jacsau.4c00271",
        "10.1021/acs.jcim.1c00075",
        "10.1021/ci034243x",
        "10.1021/cn100008c",
        "10.1021/acs.jcim.5b00654",
        "10.1186/1758-2946-3-8",
        "10.1021/acs.jcim.3c00563",
        "10.1021/acs.jmedchem.7b00717",
        "10.1093/bioinformatics/btu829",
        "10.1093/molbev/mst010",
        "10.1186/s13321-018-0324-5",
        "10.1186/s13321-021-00548-6",
    ):
        assert doi in html_all
    fame = tool_citation("fame3r")
    assert fame is not None
    assert "non-commercial" in fame.notes.lower()
    assert "University of Milan" in fame.notes
    cf = tool_citation("conforge")
    assert cf is not None
    assert "CONFORGE" in cf.name
    assert "LGPL" in cf.license_name
    bt = tool_citation("biotransformer")
    assert bt is not None
    assert "LGPL" in bt.license_name
    assert "gnu.org/licenses/lgpl-3.0" in bt.license_url
    assert "gnu.org/licenses/gpl-3.0" in tool_citation("mctoolkit").license_url  # type: ignore[union-attr]
    assert tool_citation("mctoolkit").name == "mctoolkit"  # type: ignore[union-attr]


def test_citation_html_renders_license_link() -> None:
    html = citation_html("rdkit")
    assert "RDKit" in html
    assert "License" in html
    assert "opensource.org/license/bsd-3-clause" in html
    assert "Topic unavailable" not in html


def test_open_citations_dialog_reuses_window(qapp):  # noqa: ARG001
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    open_citations_dialog(host, tool_id="gnina")
    dlg = host._citations_dialog
    assert dlg is not None
    assert "Gnina" in dlg.windowTitle()
    open_citations_dialog(host, tool_id="rdkit")
    assert host._citations_dialog is dlg
    assert "RDKit" in dlg.windowTitle()
    dlg.close()


def test_citations_dialog_does_not_cycle_with_its_host(qapp):  # noqa: ARG001
    """Host and dialog must be freed by refcounting, not the cyclic collector.

    A strong capture in the ``destroyed`` slot makes the pair a cycle, and collecting it
    deletes the Qt parent before the child wrapper, which crashes the interpreter.
    """
    import weakref

    from PySide6.QtWidgets import QWidget

    host = QWidget()
    open_citations_dialog(host, tool_id="gnina")
    host._citations_dialog.close()
    host_ref = weakref.ref(host)
    del host
    assert host_ref() is None


def test_user_guide_hotkey_registered() -> None:
    assert default_shortcuts("help.user_guides") == ["F1"]
    assert default_shortcuts("help.citations") == []
