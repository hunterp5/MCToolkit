# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Result browsers share one floating shell and preview theme."""

from __future__ import annotations

from mctoolkit.ui.browsers.chrome import (
    BROWSER_DATA_TABLE_QSS,
    BROWSER_GROUP_QSS,
    BROWSER_PREVIEW_CANVAS_QSS,
    BROWSER_PREVIEW_FRAME_QSS,
    BROWSER_PREVIEW_STRUCT_QSS,
    BrowserHostDialog,
)
from mctoolkit.ui.browsers.pair_browser import PairBrowserDialog
from mctoolkit.ui.dockable_plot import PLOT_BODY_MARGINS, PLOT_BODY_SPACING
from mctoolkit.ui.metabolite_browser import MetaboliteBrowserDialog, MetaboliteBrowserWidget
from mctoolkit.ui.mmp_browser import MmpBrowserDialog
from mctoolkit.ui.pose_browser import PoseBrowserDialog, PoseBrowserWidget
from mctoolkit.ui.random_molecule_browser import (
    RandomMoleculeBrowserDialog,
    RandomMoleculeBrowserWidget,
)
from mctoolkit.ui.sali_browser import SaliBrowserDialog
from mctoolkit.ui.selection_browser import SelectionBrowserDialog, SelectionBrowserWidget
from mctoolkit.ui.som_browser import SomBrowserDialog, SomBrowserWidget
from mctoolkit.ui.tautomer_browser import TautomerBrowserDialog, TautomerBrowserWidget
from mctoolkit.ui.protomer_browser import ProtomerBrowserDialog, ProtomerBrowserWidget


def test_dockable_browser_dialogs_share_host_shell():
    for cls in (
        SelectionBrowserDialog,
        PoseBrowserDialog,
        SomBrowserDialog,
        MetaboliteBrowserDialog,
        TautomerBrowserDialog,
        ProtomerBrowserDialog,
        RandomMoleculeBrowserDialog,
    ):
        assert issubclass(cls, BrowserHostDialog)


def test_pair_browsers_share_pair_shell():
    assert issubclass(MmpBrowserDialog, PairBrowserDialog)
    assert issubclass(SaliBrowserDialog, PairBrowserDialog)


def test_canvas_browsers_use_shared_preview_theme(qapp):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    widgets = (
        SelectionBrowserWidget(ChemistryWorkspaceWindow()),
        SomBrowserWidget(None),
        MetaboliteBrowserWidget(None),
        TautomerBrowserWidget(None),
        ProtomerBrowserWidget(None),
        RandomMoleculeBrowserWidget(None),
    )
    for panel in widgets:
        assert panel._preview_host.styleSheet() == BROWSER_PREVIEW_CANVAS_QSS
        assert panel._struct_label.styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        margins = panel.layout().contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == PLOT_BODY_MARGINS
        assert panel.layout().spacing() == PLOT_BODY_SPACING
        panel.deleteLater()


def test_pose_browser_uses_shared_frame_and_table_theme(qapp):  # noqa: ARG001
    panel = PoseBrowserWidget(None)
    assert panel._preview_host.styleSheet() == BROWSER_PREVIEW_FRAME_QSS
    assert panel._row_table.styleSheet() == BROWSER_DATA_TABLE_QSS
    panel.deleteLater()


def test_pair_browsers_use_shared_group_and_structure_theme(qapp):  # noqa: ARG001
    mmp = MmpBrowserDialog(None, [], activity_column="pIC50")
    sali = SaliBrowserDialog(None, [], activity_column="pIC50")
    for dlg in (mmp, sali):
        assert dlg._left_panel["struct"].styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        assert dlg._right_panel["struct"].styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        assert dlg._prop_box.styleSheet() == BROWSER_GROUP_QSS
        assert dlg._left_panel["box"].styleSheet() == BROWSER_GROUP_QSS
        margins = dlg.layout().contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == PLOT_BODY_MARGINS
        dlg.deleteLater()
