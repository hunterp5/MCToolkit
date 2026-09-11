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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""In-app User Manual for MolManager (TOC + Markdown topic loader)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..help_markdown import load_help_markdown, markdown_to_html_fragment, missing_topic_html
from .qt_widget_utils import make_window_minimizable

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QWidget


@dataclass(frozen=True)
class GuideEntry:
    """One help topic: stable id, short label, sidebar label, and tooltip."""

    guide_id: str
    menu_label: str
    list_label: str
    blurb: str


@dataclass(frozen=True)
class GuideSection:
    """A group of related help topics shown in the sidebar."""

    title: str
    entries: tuple[GuideEntry, ...]


def _e(guide_id: str, menu_label: str, list_label: str, blurb: str) -> GuideEntry:
    return GuideEntry(guide_id, menu_label, list_label, blurb)


GUIDE_SECTIONS: tuple[GuideSection, ...] = (
    GuideSection(
        "1 — Start here",
        (
            _e(
                "overview",
                "Overview",
                "Overview",
                "What MolManager is and how the main window is organized.",
            ),
            _e(
                "processes",
                "Processes",
                "Processes",
                "Running and queued background jobs; cancel and clear.",
            ),
            _e(
                "settings",
                "Settings",
                "Settings",
                "Theme, fonts, status bar, and keyboard shortcuts.",
            ),
        ),
    ),
    GuideSection(
        "2 — File and sessions",
        (
            _e(
                "file_open",
                "Open File",
                "Open File",
                "Load SDF, MOL, SMILES, CSV, and related formats.",
            ),
            _e(
                "file_import",
                "Import Data",
                "Import Data",
                "Append or merge data into the current table.",
            ),
            _e("file_sessions", "Sessions", "Sessions", "Open, save, new, and duplicate sessions."),
            _e("file_export", "Export", "Export", "Export all or selected rows to common formats."),
            _e(
                "file_browser",
                "Selection Browser",
                "Selection Browser",
                "Review and act on the current selection.",
            ),
        ),
    ),
    GuideSection(
        "3 — Edit and table",
        (
            _e("edit_menu", "Edit", "Edit", "Undo/redo, clipboard, and selection commands."),
            _e("table", "Table", "Table", "Columns, sorting, context menus, and precision."),
            _e(
                "tools_filter",
                "Filters",
                "Filters",
                "Filter panel cards, titles, reorder, and enable/disable.",
            ),
            _e("tools_search", "Search", "Search", "Multi-column search with AND/OR criteria."),
        ),
    ),
    GuideSection(
        "4 — Prepare and structures",
        (
            _e(
                "tools_calc_descriptors",
                "Calculate Descriptors",
                "Calculate Descriptors",
                "RDKit descriptors and related property columns.",
            ),
            _e(
                "tools_fast_prepare",
                "Fast Prepare",
                "Fast Prepare",
                "Largest fragment, optional neutralize, and redraw in one job.",
            ),
            _e(
                "tools_disconnect_fragments",
                "Disconnect Fragments",
                "Disconnect Fragments",
                "Split disconnected components into rows.",
            ),
            _e(
                "tools_add_explicit_h",
                "Add Explicit Hydrogens",
                "Add Explicit Hydrogens",
                "Expand implicit hydrogens with RDKit AddHs.",
            ),
            _e(
                "tools_remove_explicit_h",
                "Remove Explicit Hydrogens",
                "Remove Explicit Hydrogens",
                "Strip explicit hydrogens with RDKit RemoveHs.",
            ),
            _e(
                "tools_render_2d",
                "Render 2D",
                "Render 2D",
                "Regenerate 2D depictions as a background batch.",
            ),
            _e(
                "tools_protonate",
                "Protonate",
                "Protonate",
                "Dominant protomer at a chosen pH (Uni-pKa).",
            ),
            _e(
                "tools_generate_protomers",
                "Generate Protomers",
                "Generate Protomers",
                "Enumerate protomers/tautomers into the table.",
            ),
            _e(
                "tools_neutralize",
                "Neutralize",
                "Neutralize",
                "Zero net formal charge with RDKit Uncharger.",
            ),
            _e(
                "tools_calculator",
                "Calculator",
                "Calculator",
                "New numeric column from a math expression.",
            ),
            _e("tools_sketcher", "Sketcher", "Sketcher", "Draw and edit molecules interactively."),
        ),
    ),
    GuideSection(
        "5 — Conformations",
        (
            _e(
                "tools_gen_conformations",
                "Generate Conformations",
                "Generate Conformations",
                "Build 3D conformer ensembles (stochastic ETKDG).",
            ),
            _e(
                "tools_gen_conformations_systematic",
                "Systematic Conformations",
                "Systematic Conformations",
                "Build 3D ensembles with Open Babel Confab.",
            ),
            _e(
                "tools_superpose_conformers",
                "Superpose Conformers",
                "Superpose Conformers",
                "Align conformers within a molecule.",
            ),
            _e(
                "tools_superpose_structures",
                "Superpose Structures",
                "Superpose Structures",
                "Align structures across rows (MCS options).",
            ),
        ),
    ),
    GuideSection(
        "6 — Fingerprints",
        (
            _e(
                "tools_fp_similarity",
                "Fingerprint Similarity",
                "Fingerprint Similarity",
                "Similarity scores vs a query molecule.",
            ),
            _e(
                "tools_diverse_subset",
                "Diverse Subset",
                "Diverse Subset",
                "Pick a chemically diverse subset of rows.",
            ),
            _e(
                "tools_cluster",
                "Cluster",
                "Cluster",
                "Cluster molecules by fingerprint similarity.",
            ),
        ),
    ),
    GuideSection(
        "7 — Docking",
        (
            _e(
                "tools_prepare_pdb",
                "Prepare PDB",
                "Prepare PDB",
                "Clean and complete protein PDB files.",
            ),
            _e(
                "tools_prepare_pdbqt",
                "Prepare PDBQT",
                "Prepare PDBQT",
                "Build receptor/ligand PDBQT (SDF, PDB, SMILES, or table rows).",
            ),
            _e(
                "tools_easydock",
                "EasyDock",
                "EasyDock",
                "Dock table ligands with EasyDock (Smina or Vina) into a receptor box.",
            ),
            _e(
                "tools_smina",
                "Smina",
                "Smina",
                "Run Smina as a file-based CLI (no table writeback).",
            ),
        ),
    ),
    GuideSection(
        "8 — Design and modeling",
        (
            _e(
                "tools_rgroup",
                "R-Group Decomposition",
                "R-Group Decomposition",
                "Match a core and extract R-group columns.",
            ),
            _e(
                "tools_mmp",
                "MMP Transform Ledger",
                "MMP",
                "Matched molecular pair transform ledger.",
            ),
            _e(
                "tools_activity_cliff",
                "MMP Activity Cliffs",
                "Activity Cliffs",
                "Cliff scatter from Transform Ledger pairs.",
            ),
            _e(
                "tools_mmp_neighborhood",
                "MMP Pair Network",
                "Pair Network",
                "Neighborhood graph from Transform Ledger pairs.",
            ),
            _e(
                "tools_reaction_enum",
                "Reaction Enumeration",
                "Reaction Enumeration",
                "Enumerate products from reaction SMARTS.",
            ),
            _e(
                "tools_predict_som",
                "Predict SOM",
                "SOM",
                "FAME3R sites of metabolism for Phase 1, Phase 2, both, or CYP.",
            ),
            _e(
                "tools_pka",
                "Predict pKa",
                "pKa",
                "Uni-pKa macro pKa values from a structure column or SMILES.",
            ),
            _e("data_qsar", "QSAR", "QSAR", "Train and apply QSAR models on table features."),
            _e("data_mpo", "MPO Scoring", "MPO Scoring", "Multi-parameter desirability scores."),
        ),
    ),
    GuideSection(
        "9 — Random",
        (
            _e(
                "tools_random_number",
                "Random Number",
                "Random Number",
                "Fill a column with random numbers.",
            ),
            _e(
                "tools_random_molecule",
                "Random Molecule",
                "Random Molecule",
                "Generate random molecules into the table.",
            ),
        ),
    ),
    GuideSection(
        "10 — Charts and analysis",
        (
            _e(
                "data_analyze_table",
                "Analyze Table",
                "Analyze Table",
                "Summary statistics for table columns.",
            ),
            _e(
                "data_plotter",
                "Plotter",
                "Plotter",
                "Scatter, histogram, heatmap, box, violin, radar.",
            ),
            _e("data_pca", "PCA", "PCA", "Principal component analysis plot."),
            _e("data_tsne", "t-SNE", "t-SNE", "t-SNE embedding visualization."),
            _e("data_umap", "UMAP", "UMAP", "UMAP embedding visualization."),
            _e("data_som", "SOM", "Self-Organizing Map", "Self-organizing map visualization."),
            _e(
                "data_boiled_egg",
                "BOILED-Egg",
                "BOILED-Egg",
                "Brain/intestinal absorption style plot.",
            ),
            _e(
                "data_golden_triangle",
                "Golden Triangle",
                "Golden Triangle",
                "Medchem golden-triangle plot.",
            ),
            _e(
                "data_sali",
                "SALI",
                "SALI",
                "Fingerprint similarity vs |Δactivity| colored by SALI.",
            ),
        ),
    ),
    GuideSection(
        "11 — External data",
        (
            _e(
                "ext_sql", "SQL Database", "SQL Database", "Load query results from a SQL database."
            ),
            _e("ext_pubchem", "PubChem", "PubChem", "Lookup and similarity search in PubChem."),
            _e("ext_chembl", "ChEMBL", "ChEMBL", "Molecules and bioactivity from ChEMBL."),
            _e("ext_patents", "Patents", "Patents", "SureChEMBL patent chemistry similarity."),
        ),
    ),
)

GUIDE_MENU: tuple[tuple[str, str], ...] = tuple(
    (e.guide_id, e.list_label) for s in GUIDE_SECTIONS for e in s.entries
)


def iter_guide_entries() -> list[GuideEntry]:
    out: list[GuideEntry] = []
    for section in GUIDE_SECTIONS:
        out.extend(section.entries)
    return out


def guide_entry(guide_id: str) -> GuideEntry | None:
    for entry in iter_guide_entries():
        if entry.guide_id == guide_id:
            return entry
    return None


def _guide_style_sheet(palette: QPalette | None = None) -> str:
    pal = palette or QApplication.palette()
    text = pal.color(QPalette.WindowText).name()
    mid = pal.color(QPalette.Mid).name()
    base = pal.color(QPalette.Base).name()
    window = pal.color(QPalette.Window).name()
    highlight = pal.color(QPalette.Highlight).name()
    tip_bg = pal.color(QPalette.AlternateBase).name()
    tip_border = highlight
    h2_color = text
    link = highlight
    return f"""
body {{ font-family: Segoe UI, sans-serif; font-size: 13px; color: {text};
       background: {base}; margin: 12px 16px; line-height: 1.45; }}
h2 {{ color: {h2_color}; font-size: 1.35em; margin: 0 0 0.6em 0; padding-bottom: 0.35em;
     border-bottom: 2px solid {mid}; }}
h1 {{ color: {h2_color}; font-size: 1.5em; margin: 0 0 0.55em 0; padding-bottom: 0.35em;
     border-bottom: 2px solid {mid}; }}
h3 {{ color: {text}; font-size: 1.05em; margin: 1.1em 0 0.45em 0; }}
p {{ margin: 0.55em 0; }}
ul, ol {{ margin: 0.4em 0 0.9em 0; padding-left: 1.35em; }}
li {{ margin: 0.4em 0; }}
b {{ color: {text}; }}
code {{ background: {window}; color: {text}; padding: 1px 5px; border-radius: 3px;
       font-size: 0.92em; border: 1px solid {mid}; }}
pre {{ background: {window}; border: 1px solid {mid}; border-radius: 4px;
      padding: 8px 10px; overflow-x: auto; }}
pre code {{ border: none; padding: 0; background: transparent; }}
table {{ border-collapse: collapse; margin: 0.6em 0 1em 0; width: 100%; }}
th, td {{ border: 1px solid {mid}; padding: 4px 8px; text-align: left; }}
th {{ background: {window}; }}
.tip {{ background: {tip_bg}; border-left: 3px solid {tip_border}; padding: 8px 12px;
       margin: 0.8em 0; color: {text}; }}
a {{ color: {link}; }}
hr {{ border: none; border-top: 1px solid {mid}; margin: 1em 0; }}
"""


def guide_html(guide_id: str, palette: QPalette | None = None) -> str:
    """Return a full HTML document for the given help topic."""
    md = load_help_markdown(guide_id)
    if md is None:
        body = missing_topic_html(guide_id)
    else:
        body = markdown_to_html_fragment(md)
    return (
        f"<html><head><style>{_guide_style_sheet(palette)}</style></head><body>{body}</body></html>"
    )


def _populate_guide_list(lst: QListWidget, *, select_guide_id: str | None = None) -> None:
    lst.clear()
    select_row = 0
    row = 0
    header_font = QFont(lst.font())
    header_font.setBold(True)

    for section in GUIDE_SECTIONS:
        header = QListWidgetItem(section.title)
        header.setFlags(Qt.NoItemFlags)
        header.setFont(header_font)
        header.setForeground(lst.palette().mid())
        lst.addItem(header)
        row += 1

        for entry in section.entries:
            it = QListWidgetItem(entry.list_label)
            it.setData(Qt.UserRole, entry.guide_id)
            it.setToolTip(entry.blurb)
            lst.addItem(it)
            if select_guide_id and entry.guide_id == select_guide_id:
                select_row = row
            row += 1

    lst.setCurrentRow(select_row)


def open_user_guide_dialog(parent: QWidget | None, guide_id: str | None = "overview") -> None:
    """Open the user guide (modeless). Reuses an existing window when possible."""
    topic = (guide_id or "overview").strip() or "overview"
    host = parent
    dlg = getattr(host, "_user_guide_dialog", None) if host is not None else None
    if dlg is not None:
        try:
            _show_guide_dialog(dlg, topic)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            if host is not None:
                host._user_guide_dialog = None

    dlg = QDialog(parent)
    dlg.setWindowTitle("MolManager — Help")
    dlg.resize(900, 620)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)

    outer = QVBoxLayout(dlg)
    content = QHBoxLayout()
    lst = QListWidget()
    lst.setMinimumWidth(280)
    _populate_guide_list(lst, select_guide_id=topic)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    content.addWidget(lst)
    content.addWidget(browser, 1)
    outer.addLayout(content)

    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dlg.close)
    outer.addWidget(close_btn)

    dlg._guide_list = lst  # type: ignore[attr-defined]
    dlg._guide_browser = browser  # type: ignore[attr-defined]

    def on_pick(current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        gid = current.data(Qt.UserRole)
        if isinstance(gid, str):
            _show_guide_dialog(dlg, gid)

    lst.currentItemChanged.connect(on_pick)
    make_window_minimizable(dlg)

    if host is not None:
        host._user_guide_dialog = dlg
        dlg.destroyed.connect(lambda: setattr(host, "_user_guide_dialog", None))

    _show_guide_dialog(dlg, topic)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def _show_guide_dialog(dlg: QDialog, guide_id: str) -> None:
    lst = getattr(dlg, "_guide_list", None)
    browser = getattr(dlg, "_guide_browser", None)
    if browser is not None:
        browser.setHtml(guide_html(guide_id, dlg.palette()))
    entry = guide_entry(guide_id)
    if entry is not None:
        dlg.setWindowTitle(f"MolManager — Help: {entry.menu_label}")
    else:
        dlg.setWindowTitle("MolManager — Help")
    if lst is not None:
        for i in range(lst.count()):
            it = lst.item(i)
            if it is not None and it.data(Qt.UserRole) == guide_id:
                lst.setCurrentRow(i)
                break
