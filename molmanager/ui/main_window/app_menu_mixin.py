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

"""Main menubar, dock-results chrome, and workspace dialog openers."""

from __future__ import annotations

import sys

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QWidget,
)

from ...config import load_config
from ..citations_dialog import open_citations_dialog
from ..user_guides import open_user_guide_dialog

_HELP_HOTKEY_IDS = frozenset({"help.user_guides", "help.citations"})


def _help_glyph_icon(*, size: int, ink: QColor, paper: QColor) -> QIcon:
    """Filled circular badge with a bold question mark (classic help control)."""
    dpr = 2.0
    side = max(12, int(size))
    px = max(1, int(round(side * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(dpr, dpr)
    s = float(side)
    pad = max(0.5, s * 0.05)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    painter.drawEllipse(QRectF(pad, pad, s - 2.0 * pad, s - 2.0 * pad))

    stroke = max(1.7, s * 0.13)
    pen = QPen(paper, stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    bowl = QRectF(s * 0.30, s * 0.16, s * 0.40, s * 0.40)
    # Clockwise from the left of the bowl, over the top, down to the stem.
    painter.drawArc(bowl, 185 * 16, -255 * 16)
    cx = s * 0.50
    painter.drawLine(QPointF(cx, s * 0.52), QPointF(cx, s * 0.62))
    painter.setPen(Qt.NoPen)
    painter.setBrush(paper)
    painter.drawEllipse(QPointF(cx, s * 0.76), max(1.35, s * 0.075), max(1.35, s * 0.075))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


class AppMenuMixin:
    def init_menubar(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        file_menu.addAction(
            self._bind_hotkey(
                "file.open",
                QAction("&Open File...", self, triggered=self.open_file_dialog),
            )
        )
        file_menu.addAction(
            self._bind_hotkey(
                "file.export_all",
                QAction("&Save File...", self, triggered=lambda: self.run_export(False)),
            )
        )
        file_menu.addAction(
            QAction("Save Selected...", self, triggered=lambda: self.run_export(True))
        )
        file_menu.addAction(
            QAction("Import &Data...", self, triggered=self.open_import_file_dialog)
        )
        file_menu.addSeparator()
        file_menu.addAction(QAction("Open Session…", self, triggered=self.open_session_file))
        file_menu.addAction(QAction("Save Session…", self, triggered=self.save_session_as))
        file_menu.addAction(QAction("New Session", self, triggered=self.new_session))
        file_menu.addAction(QAction("Duplicate Session", self, triggered=self.duplicate_session))
        edit = mb.addMenu("&Edit")
        act_undo = self._bind_hotkey("edit.undo", self._undo_stack.createUndoAction(self))
        act_redo = self._bind_hotkey("edit.redo", self._undo_stack.createRedoAction(self))
        edit.addAction(act_undo)
        edit.addAction(act_redo)
        self.addAction(act_undo)
        self.addAction(act_redo)
        edit.addSeparator()
        edit.addAction(
            self._bind_hotkey("edit.copy", QAction("&Copy", self, triggered=self.edit_copy))
        )
        edit.addAction(
            self._bind_hotkey("edit.paste", QAction("&Paste", self, triggered=self.edit_paste))
        )
        act_del_sel = self._bind_hotkey(
            "edit.delete_selection",
            QAction("Delete &Selection", self, triggered=self.edit_delete_selection),
        )
        act_del_sel.setToolTip(
            "Delete selected rows, selected columns, or cell values, depending on the selection. "
            "When both rows and columns are selected, you choose which to delete."
        )
        edit.addAction(act_del_sel)
        edit.addSeparator()
        act_invert_sel = self._bind_hotkey(
            "edit.invert_selection",
            QAction("Invert Selection", self, triggered=self.invert_table_selection),
        )
        act_invert_sel.setToolTip(
            "Select all rows that are not currently selected (entire table, including rows hidden by filters)."
        )
        edit.addAction(act_invert_sel)
        act_clear_sel = self._bind_hotkey(
            "edit.clear_selection",
            QAction("Clear Selection", self, triggered=self.clear_table_selection),
        )
        act_clear_sel.setToolTip("Clear the current cell/row selection (Ctrl+Shift+D).")
        edit.addAction(act_clear_sel)
        edit.addAction(
            self._bind_hotkey(
                "edit.clear_table",
                QAction("Clear Table…", self, triggered=self.clear_table_after_confirm),
            )
        )
        tools = mb.addMenu("&Tools")
        tools.setToolTipsVisible(True)

        act_calc_desc = self._bind_hotkey(
            "tools.calculate_descriptors",
            QAction("Calculate Descriptors…", self, triggered=self.open_calc),
        )
        act_calc_desc.setToolTip(
            "Compute RDKit molecular descriptors (including 3D shape/SASA from confs) "
            "and append them as columns (selected or visible rows)."
        )
        tools.addAction(act_calc_desc)
        tools.addSeparator()

        prepare_menu = tools.addMenu("&Prepare Structures")
        prepare_menu.setToolTipsVisible(True)
        for title, slot, tip, hk_id in (
            (
                "Fast Prepare…",
                self.run_fast_prepare,
                "Disconnect largest fragment, optionally neutralize, and redraw 2D images in one background job.",
                None,
            ),
            (
                None,
                None,
                None,
                None,
            ),
            (
                "Disconnect Largest Fragments…",
                self.run_disconnect_fragments,
                "Split disconnected structure fragments into separate rows, keeping the heaviest fragment.",
                None,
            ),
        ):
            if title is None:
                prepare_menu.addSeparator()
                continue
            act = QAction(title, self, triggered=slot)
            if hk_id:
                self._bind_hotkey(hk_id, act)
            act.setToolTip(tip)
            prepare_menu.addAction(act)

        protonate_menu = prepare_menu.addMenu("Protonate")
        protonate_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "Protonate…",
                self.run_protonate,
                "Generate the dominant protomer (Uni-pKa) into a column and optionally render it like Structure.",
            ),
            (
                "Generate Protomers…",
                self.open_protomer_generator,
                "Enumerate protomers or tautomers from structures and add results to the table.",
            ),
            (
                "Neutralize…",
                self.run_neutralize,
                "Adjust protonation so the net formal charge is zero (RDKit Uncharger); updates the target column.",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            protonate_menu.addAction(act)

        hydrogens_menu = prepare_menu.addMenu("Explicit Hydrogens")
        hydrogens_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "Add…",
                self.run_add_explicit_hydrogens,
                "Expand implicit hydrogens to explicit H atoms in the target column (RDKit AddHs).",
            ),
            (
                "Remove…",
                self.run_remove_explicit_hydrogens,
                "Remove explicit H atoms from structures in the target column (RDKit RemoveHs).",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            hydrogens_menu.addAction(act)

        act_render_2d = self._bind_hotkey(
            "tools.render_2d",
            QAction("Render 2D…", self, triggered=self.run_render_2d_structures),
        )
        act_render_2d.setToolTip(
            "Regenerate 2D structure drawings for selected rows as a background batch (see Processes)."
        )
        prepare_menu.addAction(act_render_2d)

        self._act_custom_calc = self._bind_hotkey(
            "tools.calculator",
            QAction("Calculator…", self, triggered=self.open_calculator),
        )
        self._act_custom_calc.setToolTip(
            "Add a numeric column from a math expression using existing column names (e.g. sqrt, log10, exp)."
        )
        if load_config().disable_custom_calc:
            self._act_custom_calc.setEnabled(False)
            self._act_custom_calc.setToolTip(
                "Calculator disabled by MOLMANAGER_DISABLE_CUSTOM_CALC."
            )

        conformations_menu = tools.addMenu("&Conformations")
        conformations_menu.setToolTipsVisible(True)
        act_gen_conf = QAction(
            "Stochastic…",
            self,
            triggered=self.open_generate_conformations,
        )
        act_gen_conf.setToolTip(
            "Build ensembles with RDKit ETKDG (stochastic distance geometry), then minimize and prune."
        )
        conformations_menu.addAction(act_gen_conf)
        act_sys_conf = QAction(
            "Systematic…",
            self,
            triggered=self.open_systematic_conformations,
        )
        act_sys_conf.setToolTip(
            "Build ensembles with Open Babel Confab (systematic torsion search)."
        )
        conformations_menu.addAction(act_sys_conf)
        conformations_menu.addSeparator()
        act_superpose = QAction("&Superpose…", self, triggered=self.open_superpose)
        act_superpose.setToolTip(
            "Overlay conformers within a row or structures across rows, in 3D (spatial) or 2D (topological)."
        )
        conformations_menu.addAction(act_superpose)

        fp_menu = tools.addMenu("&Fingerprints")
        fp_menu.setToolTipsVisible(True)

        act_fp_sim = self._bind_hotkey(
            "tools.fingerprint_similarity",
            QAction("Fingerprint Similarity...", self, triggered=self.open_fp_similarity),
        )
        act_fp_sim.setToolTip("Search the table by 2D fingerprint similarity to a query structure.")
        fp_menu.addAction(act_fp_sim)

        act_diverse = QAction("Diverse Subset…", self, triggered=self.open_diverse_subset)
        act_diverse.setToolTip(
            "Pick a maximally diverse subset of compounds (MaxMin on fingerprint Tanimoto distance)."
        )
        fp_menu.addAction(act_diverse)

        act_cluster = self._bind_hotkey(
            "data.cluster",
            QAction("Cluster…", self, triggered=self.open_cluster_dialog),
        )
        act_cluster.setToolTip(
            "Cluster compounds by fingerprint (K-Means, Butina, sphere exclusion, etc.)."
        )
        fp_menu.addAction(act_cluster)

        predict_menu = tools.addMenu("&Predict")
        predict_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "pKa…",
                self.open_pka_predictor,
                "Estimate ionization / pKa-related properties when the predictor is available.",
            ),
            (
                "Permeability…",
                self.open_permeability_predictor,
                "Predict Caco-2 and MDCK permeability / efflux endpoints (optional Chemprop install).",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            predict_menu.addAction(act)

        som_menu = predict_menu.addMenu("SOM")
        som_menu.setToolTipsVisible(True)
        act_som_predict = QAction("Predict…", self, triggered=self.open_som_predictor)
        act_som_predict.setToolTip(
            "Predict sites of metabolism with FAME3R and draw a highlighted atom map."
        )
        som_menu.addAction(act_som_predict)
        act_som_viewer = QAction("Viewer", self, triggered=self.open_som_viewer)
        act_som_viewer.setToolTip(
            "Open the SOM map browser when Predict SOM results are in the table."
        )
        act_som_viewer.setEnabled(False)
        self._act_som_viewer = act_som_viewer
        som_menu.addAction(act_som_viewer)

        met_menu = predict_menu.addMenu("Metabolites")
        met_menu.setToolTipsVisible(True)
        act_met_predict = QAction("Predict…", self, triggered=self.open_biotransformer_predictor)
        act_met_predict.setToolTip("Predict metabolite structures with a local BioTransformer JAR.")
        met_menu.addAction(act_met_predict)
        act_met_viewer = QAction("Viewer", self, triggered=self.open_metabolite_viewer)
        act_met_viewer.setToolTip(
            "Open the metabolite browser when Predict Metabolites results are in the table."
        )
        act_met_viewer.setEnabled(False)
        self._act_metabolite_viewer = act_met_viewer
        met_menu.addAction(act_met_viewer)
        predict_menu.aboutToShow.connect(self._sync_predict_viewer_actions)

        dock_menu = tools.addMenu("&Dock")
        dock_menu.setToolTipsVisible(True)
        prepare_menu = dock_menu.addMenu("Prepare")
        prepare_menu.setToolTipsVisible(True)
        act_dock_prepare = QAction("PDBQT…", self, triggered=self.open_dock_prepare)
        act_dock_prepare.setToolTip(
            "Generate receptor and/or ligand PDBQT (receptor PDB; ligand SDF, PDB, SMILES, or table rows)."
        )
        prepare_menu.addAction(act_dock_prepare)
        act_dock_prepare_pdb = QAction("Receptor PDB…", self, triggered=self.open_dock_prepare_pdb)
        act_dock_prepare_pdb.setToolTip(
            "Clean a receptor PDB with PDBFixer (remove ligands/waters, add atoms and hydrogens) "
            "before PDBQT conversion or docking."
        )
        prepare_menu.addAction(act_dock_prepare_pdb)
        dock_menu.addSeparator()
        act_dock_smina = QAction("Smina…", self, triggered=self.open_smina_dock)
        act_dock_smina.setToolTip(
            "Run Smina as a file-based CLI on PDBQT inputs (log only; no table writeback)."
        )
        dock_menu.addAction(act_dock_smina)
        dock_menu.addSeparator()
        act_dock_viewer = QAction("Viewer", self, triggered=self.open_dock_results_viewer)
        act_dock_viewer.setToolTip(
            "Show the last docking results window, even after it has been closed."
        )
        act_dock_viewer.setEnabled(False)
        self._act_dock_viewer = act_dock_viewer
        dock_menu.addAction(act_dock_viewer)

        reaction_menu = tools.addMenu("&Reaction")
        reaction_menu.setToolTipsVisible(True)
        act_reaction_extract = QAction(
            "Extract…",
            self,
            triggered=self.open_reaction_extract,
        )
        act_reaction_extract.setToolTip(
            "Split a reaction SMARTS / SMIRKS column into individual reactant and/or "
            "product columns."
        )
        reaction_menu.addAction(act_reaction_extract)
        decomp_menu = reaction_menu.addMenu("&R-Group Decomposition")
        decomp_menu.setToolTipsVisible(True)
        for title, slot, tip in (
            (
                "Core-Based Decomposition…",
                self.open_core_based_decomposition,
                "Decompose structures against a labeled core scaffold (substituent columns).",
            ),
            (
                "BRICS Decomposition…",
                self.open_brics_decomposition,
                "Split structures into BRICS retrosynthetic fragments (new SMILES columns).",
            ),
            (
                "BRICS Recomposition…",
                self.open_brics_recomposition,
                "Combine BRICS fragment columns into new product structures (new rows).",
            ),
            (
                "RECAP Decomposition…",
                self.open_recap_decomposition,
                "Split structures into RECAP retrosynthetic fragments (new SMILES columns).",
            ),
            (
                "RECAP Recomposition…",
                self.open_recap_recomposition,
                "Combine RECAP fragment columns into new product structures (new rows).",
            ),
        ):
            act = QAction(title, self, triggered=slot)
            act.setToolTip(tip)
            decomp_menu.addAction(act)

        act_reaction_enum = QAction(
            "Reaction Based Enumeration…",
            self,
            triggered=self.open_reaction_enumeration,
        )
        act_reaction_enum.setToolTip(
            "Run a named reaction (Suzuki, Buchwald, amide coupling, etc.) across two reactant "
            "pools from structure files or pasted SMILES, then append products to the table "
            "and/or an SDF file."
        )
        reaction_menu.addAction(act_reaction_enum)

        tools.addSeparator()
        tools.addAction(self._act_custom_calc)
        random_menu = tools.addMenu("&Random")
        random_menu.setToolTipsVisible(True)
        act_random_number = QAction("Number…", self, triggered=self.open_random_number_dialog)
        act_random_number.setToolTip(
            "Fill a column with random numbers (uniform, integer, or normal) for all or selected rows."
        )
        random_menu.addAction(act_random_number)
        act_random_molecule = QAction("Molecule…", self, triggered=self.open_random_molecule_dialog)
        act_random_molecule.setToolTip(
            "Fetch a specified number of random small molecules from ChEMBL and add them to the table."
        )
        random_menu.addAction(act_random_molecule)

        tools.addSeparator()
        filter_menu = tools.addMenu("&Filter")
        filter_menu.setToolTipsVisible(True)
        self._act_toggle_filter_panel = self._bind_hotkey(
            "tools.toggle_filter_panel",
            QAction("Toggle Panel", self, triggered=self.toggle_filter_panel),
        )
        self._act_toggle_filter_panel.setToolTip("Show or hide the filter panel (Ctrl+Shift+L).")
        self.addAction(self._act_toggle_filter_panel)
        filter_menu.addAction(self._act_toggle_filter_panel)
        filter_menu.addSeparator()
        act_sub = QAction(
            "Add Substructure", self, triggered=lambda: self.add_substructure_filter_card()
        )
        act_sub.setToolTip(
            "Add a filter card that matches a SMARTS substructure in the Structure column."
        )
        filter_menu.addAction(act_sub)
        act_slider = QAction("Add Slider", self, triggered=lambda: self.add_filter_card())
        act_slider.setToolTip("Add a numeric range slider filter for a column.")
        filter_menu.addAction(act_slider)
        act_txt = QAction("Add Text", self, triggered=lambda: self.add_text_filter_card())
        act_txt.setToolTip("Add a text contains / equals filter for a column.")
        filter_menu.addAction(act_txt)
        act_cat = QAction("Add Category", self, triggered=lambda: self.add_category_filter_card())
        act_cat.setToolTip("Add a categorical multi-select filter for a column.")
        filter_menu.addAction(act_cat)
        filter_menu.addSeparator()
        act_enable_all_filters = QAction(
            "Enable All Filters", self, triggered=self.enable_all_filters_keep_panel
        )
        act_enable_all_filters.setToolTip("Turn on every filter card in the panel.")
        filter_menu.addAction(act_enable_all_filters)
        act_disable_all_filters = QAction(
            "Disable All Filters", self, triggered=self.disable_all_filters_keep_panel
        )
        act_disable_all_filters.setToolTip(
            "Turn off every filter card. Cards stay in the panel; use On on each card to enable again."
        )
        filter_menu.addAction(act_disable_all_filters)
        act_delete_all_filters = QAction(
            "Delete All Filters", self, triggered=self.delete_all_filters_from_panel
        )
        act_delete_all_filters.setToolTip("Remove every filter card from the panel.")
        filter_menu.addAction(act_delete_all_filters)
        act_search = self._bind_hotkey(
            "tools.search",
            QAction("&Search…", self, triggered=self.toggle_table_search_panel),
        )
        act_search.setToolTip(
            "Open or hide the in-table search panel (Ctrl+F). Queries stay until deleted with −."
        )
        tools.addAction(act_search)

        tools.addSeparator()
        act_sketch = self._bind_hotkey(
            "tools.sketcher",
            QAction("&Sketcher…", self, triggered=self.open_sketcher),
        )
        act_sketch.setToolTip("Open the structure sketcher to draw or edit molecules.")
        tools.addAction(act_sketch)

        protein_menu = mb.addMenu("&Protein")
        protein_menu.setToolTipsVisible(True)
        act_protein_viewer = QAction("&Viewer", self, triggered=self.open_protein_viewer)
        act_protein_viewer.setToolTip(
            "Load a PDB, mmCIF, or other crystallographic file and inspect chains in 3D."
        )
        protein_menu.addAction(act_protein_viewer)
        act_protein_seq = QAction("&Sequence…", self, triggered=self.open_protein_sequence)
        act_protein_seq.setToolTip(
            "Align amino-acid sequences with MAFFT (FASTA, paste, or Protein Viewer chains)."
        )
        protein_menu.addAction(act_protein_seq)

        data_menu = mb.addMenu("&Data")
        table_menu = data_menu.addMenu("&Table")
        table_menu.addAction(
            self._bind_hotkey(
                "data.analyze_table",
                QAction("Statistics…", self, triggered=self.open_data_analysis),
            )
        )
        act_split_col = self._bind_hotkey(
            "data.split_column",
            QAction("Split Column…", self, triggered=self.open_split_column_dialog),
        )
        act_split_col.setToolTip(
            "Split a delimited column (comma, tab, space, semicolon, …) into new columns."
        )
        table_menu.addAction(act_split_col)
        act_join_col = self._bind_hotkey(
            "data.join_columns",
            QAction("Join Columns…", self, triggered=self.open_join_columns_dialog),
        )
        act_join_col.setToolTip("Join two columns into one new column with a chosen delimiter.")
        table_menu.addAction(act_join_col)
        data_menu.addSeparator()
        act_qsar = QAction("QSAR…", self, triggered=self.open_qsar_dialog)
        act_qsar.setToolTip(
            "Train regression or classification models on activity vs descriptors or fingerprints."
        )
        data_menu.addAction(act_qsar)
        act_mpo = QAction("MPO Scoring…", self, triggered=self.open_mpo_scoring_dialog)
        act_mpo.setToolTip(
            "Score rows with linear, Gaussian, or step desirability functions and combine into an overall MPO score."
        )
        data_menu.addAction(act_mpo)
        data_menu.addSeparator()
        act_sali = QAction("SALI…", self, triggered=self.open_sali_dialog)
        act_sali.setToolTip(
            "Plot fingerprint similarity vs |Δactivity| colored by SALI "
            "(|Δ| / (1 − similarity)). Click a point to select the pair."
        )
        data_menu.addAction(act_sali)
        act_mmp = QAction("&MMP…", self, triggered=self.open_mmp_dialog)
        act_mmp.setToolTip(
            "Find matched molecular pairs (RDKit MMPA) and open the transform ledger "
            "ranked by support and activity effect."
        )
        data_menu.addAction(act_mmp)
        data_menu.addSeparator()
        act_plot = self._bind_hotkey(
            "data.plotter",
            QAction("&Plotter…", self, triggered=self.open_plot),
        )
        act_plot.setToolTip("Open the plotter or show the docked plot panel.")
        data_menu.addAction(act_plot)
        data_menu.addSeparator()
        medchem_menu = data_menu.addMenu("&MedChem")
        medchem_menu.setToolTipsVisible(True)
        medchem_menu.addAction(
            QAction("BOILED-Egg plot…", self, triggered=self.open_boiled_egg_plot)
        )
        medchem_menu.addAction(
            QAction("Golden Triangle plot…", self, triggered=self.open_golden_triangle_plot)
        )
        dimred_menu = data_menu.addMenu("&Dimensionality Reduction")
        dimred_menu.setToolTipsVisible(True)
        dimred_menu.addAction(
            QAction("Principal Component Analysis…", self, triggered=self.open_pca_dialog)
        )
        dimred_menu.addAction(
            QAction("t-SNE Visualization…", self, triggered=self.open_tsne_dialog)
        )
        dimred_menu.addAction(QAction("UMAP Visualization…", self, triggered=self.open_umap_dialog))
        dimred_menu.addAction(QAction("Self-Organizing Map…", self, triggered=self.open_som_dialog))
        data_menu.addSeparator()
        act_browser = self._bind_hotkey(
            "file.browser",
            QAction("&Browser…", self, triggered=self.open_selection_browser),
        )
        act_browser.setToolTip("Open the selection browser to review and act on selected rows.")
        data_menu.addAction(act_browser)

        ext_menu = mb.addMenu("E&xternal")
        ext_menu.addAction(
            QAction("Connect to SQL database…", self, triggered=self.open_external_db)
        )
        ext_menu.addSeparator()
        ext_menu.addAction(QAction("Query PubChem…", self, triggered=self.open_pubchem))
        ext_menu.addAction(QAction("Query ChEMBL…", self, triggered=self.open_chembl))
        ext_menu.addAction(QAction("Query Patents…", self, triggered=self.open_patent_query))

        self._init_settings_menu(mb)

        self._act_user_guide = self._bind_hotkey(
            "help.user_guides",
            QAction("&User Guide", self),
        )
        self._act_user_guide.setToolTip("Open MolManager help (F1).")
        self._act_user_guide.triggered.connect(lambda: open_user_guide_dialog(self))
        self.addAction(self._act_user_guide)

        self._act_citations = self._bind_hotkey(
            "help.citations",
            QAction("&Citations", self),
        )
        self._act_citations.setToolTip("Open papers and licenses for tools used in MolManager.")
        self._act_citations.triggered.connect(lambda: open_citations_dialog(self))
        self.addAction(self._act_citations)

        # Native Windows menu bars can swallow clicks meant for the corner widget; use in-window bar.
        if sys.platform == "win32":
            mb.setNativeMenuBar(False)

        corner = QWidget(mb)
        corner_ly = QHBoxLayout(corner)
        corner_ly.setContentsMargins(0, 0, 4, 0)

        btn_layout = QToolButton(corner)
        btn_layout.setText("Layout")
        btn_layout.setToolTip("Choose how the table and plot panes are arranged.")
        btn_layout.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_layout.setAutoRaise(True)
        btn_layout.setFocusPolicy(Qt.NoFocus)
        btn_layout.setFont(mb.font())
        btn_layout.clicked.connect(self.open_workspace_layout_picker)
        self._btn_workspace_layout = btn_layout
        corner_ly.addWidget(btn_layout)

        btn_proc = QToolButton(corner)
        btn_proc.setText("Processes")
        btn_proc.setToolTip(
            "View queued background jobs (conformers, descriptors, import, export, …)."
        )
        btn_proc.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_proc.setAutoRaise(True)
        btn_proc.setFocusPolicy(Qt.NoFocus)
        btn_proc.setFont(mb.font())
        btn_proc.clicked.connect(self.open_processes_dialog)
        self._btn_processes = btn_proc
        corner_ly.addWidget(btn_proc)

        btn_help = QToolButton(corner)
        btn_help.setToolTip("User Guide and Citations (F1 opens the guide).")
        btn_help.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn_help.setPopupMode(QToolButton.InstantPopup)
        btn_help.setAutoRaise(True)
        btn_help.setFocusPolicy(Qt.NoFocus)
        help_menu = QMenu(btn_help)
        help_menu.addAction(self._act_user_guide)
        help_menu.addAction(self._act_citations)
        btn_help.setMenu(help_menu)
        btn_help.setStyleSheet(
            "QToolButton { padding: 0px; margin: 0px; }"
            "QToolButton::menu-indicator { image: none; width: 0px; }"
        )
        self._btn_help = btn_help
        self._help_menu = help_menu
        corner_ly.addWidget(btn_help)
        self._sync_help_glyph_icon()
        mb.setCornerWidget(corner, Qt.TopRightCorner)
        self._sync_main_toolbar_for_table_ready()

    def apply_dock_results_chrome(self) -> None:
        """Keep File → Save File / Save Selected; drop the rest of the toolbar."""
        self._dock_results_mode = True
        mb = self.menuBar()
        mb.clear()
        file_menu = mb.addMenu("&File")
        export_all = (getattr(self, "_hotkey_actions", {}) or {}).get("file.export_all")
        if export_all is None:
            export_all = self._bind_hotkey(
                "file.export_all",
                QAction("&Save File...", self, triggered=lambda: self.run_export(False)),
            )
        else:
            export_all.setText("&Save File...")
        file_menu.addAction(export_all)
        file_menu.addAction(
            QAction("Save Selected...", self, triggered=lambda: self.run_export(True))
        )
        self._add_dock_view_menu(mb)
        keep = {"file.export_all"}
        for action_id, action in list(getattr(self, "_hotkey_actions", {}).items()):
            if action_id in keep or action is None:
                continue
            try:
                action.setShortcut(QKeySequence())
                action.setEnabled(False)
            except RuntimeError:
                pass
        for btn in (
            getattr(self, "_btn_workspace_layout", None),
            getattr(self, "_btn_processes", None),
            getattr(self, "_btn_help", None),
        ):
            if btn is not None:
                btn.hide()
        corner = mb.cornerWidget(Qt.TopRightCorner)
        if corner is not None:
            corner.hide()
        if sys.platform == "win32":
            mb.setNativeMenuBar(False)

    def _add_dock_view_menu(self, mb) -> None:
        """View → Render submenu for receptor / ligand / pocket drawing styles."""
        from ..dock_complex_viewer import (
            DEFAULT_RENDER_STYLES,
            RENDER_COMPONENT_LABELS,
            RENDER_STYLE_CHOICES,
        )

        view_menu = mb.addMenu("&View")
        render_menu = view_menu.addMenu("&Render")
        render_menu.setToolTipsVisible(True)
        render_menu.setToolTip("Choose how each component of the 3D complex is drawn.")
        self._dock_render_groups = {}
        for component, choices in RENDER_STYLE_CHOICES.items():
            sub = render_menu.addMenu(RENDER_COMPONENT_LABELS[component])
            group = QActionGroup(self)
            group.setExclusive(True)
            default = DEFAULT_RENDER_STYLES[component]
            for style_id, label in choices:
                act = QAction(label, self)
                act.setCheckable(True)
                act.setChecked(style_id == default)
                act.setData((component, style_id))
                group.addAction(act)
                sub.addAction(act)
            group.triggered.connect(self._on_dock_render_style_triggered)
            self._dock_render_groups[component] = group
        view_menu.addSeparator()
        pocket_act = QAction("Pocket View", self)
        pocket_act.setToolTip(
            "Show nearby amino acids as ball-and-stick with residue labels, and zoom to the ligand."
        )
        pocket_act.triggered.connect(self._on_dock_pocket_view)
        view_menu.addAction(pocket_act)

    def _sync_dock_render_menu_checks(self, styles: dict) -> None:
        groups = getattr(self, "_dock_render_groups", None) or {}
        for component, group in groups.items():
            want = (styles or {}).get(component)
            group.blockSignals(True)
            try:
                for act in group.actions():
                    data = act.data()
                    act.setChecked(bool(data) and data[1] == want)
            finally:
                group.blockSignals(False)

    def _on_dock_pocket_view(self) -> None:
        viewer = getattr(self, "_dock_complex_viewer", None)
        apply = getattr(viewer, "apply_pocket_view", None) if viewer is not None else None
        if callable(apply):
            apply()
        if viewer is not None:
            self._sync_dock_render_menu_checks(viewer.render_styles())

    def _on_dock_render_style_triggered(self, action: QAction) -> None:
        data = action.data() if action is not None else None
        if not data or len(data) != 2:
            return
        component, style = data
        viewer = getattr(self, "_dock_complex_viewer", None)
        setter = getattr(viewer, "set_render_style", None) if viewer is not None else None
        if callable(setter):
            setter(str(component), str(style))

    def _set_ingest_loading(self, loading: bool) -> None:
        """Track file/import ingest and gray out the main toolbar until the table is ready."""
        self._ingest_loading = bool(loading)
        self._sync_main_toolbar_for_table_ready()
        self._sync_status_chrome_for_workspace()

    def _sync_help_glyph_icon(self) -> None:
        """Paint the Help glyph with the current menubar font and text color."""
        btn = getattr(self, "_btn_help", None)
        if btn is None:
            return
        mb = self.menuBar()
        size = max(13, int(round(mb.fontMetrics().height() * 0.80)))
        ink = mb.palette().color(QPalette.WindowText)
        paper = mb.palette().color(QPalette.Window)
        btn.setIcon(_help_glyph_icon(size=size, ink=ink, paper=paper))
        btn.setIconSize(QSize(size, size))

    def _sync_main_toolbar_for_table_ready(self) -> None:
        """Disable File/Edit/Tools menus and Layout while ``_ingest_loading``; keep Processes/Help usable."""
        if getattr(self, "_dock_results_mode", False):
            return
        enabled = not bool(getattr(self, "_ingest_loading", False))
        mb = self.menuBar()
        for action in mb.actions():
            menu = action.menu()
            if menu is not None:
                menu.setEnabled(enabled)
            else:
                action.setEnabled(enabled)
        calc = getattr(self, "_act_custom_calc", None)
        calc_blocked = bool(load_config().disable_custom_calc)
        for action_id, action in getattr(self, "_hotkey_actions", {}).items():
            if action is None:
                continue
            if action_id in _HELP_HOTKEY_IDS:
                action.setEnabled(True)
            elif action is calc and calc_blocked:
                action.setEnabled(False)
            else:
                action.setEnabled(enabled)
        layout_btn = getattr(self, "_btn_workspace_layout", None)
        if layout_btn is not None:
            layout_btn.setEnabled(enabled)
        # Processes and Help stay enabled so the user can cancel a long open/import or read the manual.

    def open_protein_viewer(self):
        """Open the Protein Viewer window (3Dmol.js + chain Manager)."""
        return self._ensure_protein_viewer(show=True)

    def _ensure_protein_viewer(self, *, show: bool = True):
        """Create or reuse the Protein Viewer; pass ``show=False`` to preload without raising it."""
        from ..protein_viewer import ProteinViewerDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _on_destroyed() -> None:
            self._protein_viewer_dialog = None

        reuse_or_show_modeless_singleton(
            self,
            "_protein_viewer_dialog",
            lambda: ProteinViewerDialog(self),
            _on_destroyed,
            show=show,
        )
        return self._protein_viewer_dialog

    def open_protein_sequence(self):
        """Open the Protein Sequence MSA window (independent of Viewer Sequence)."""
        from ..dialogs.protein_sequence_msa import ProteinSequenceMsaDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _on_destroyed() -> None:
            self._protein_msa_dialog = None

        reuse_or_show_modeless_singleton(
            self,
            "_protein_msa_dialog",
            lambda: ProteinSequenceMsaDialog(self),
            _on_destroyed,
            show=True,
        )
        return self._protein_msa_dialog

    def open_workspace_layout_picker(self) -> None:
        """Show the graphic layout picker and apply the chosen preset."""
        from ..dialogs.workspace_layout_picker import WorkspaceLayoutPickerDialog

        mgr = getattr(self, "_workspace_layout", None)
        current = mgr.layout_id if mgr is not None else None
        dlg = WorkspaceLayoutPickerDialog(self, current_layout_id=current)
        dlg.layout_chosen.connect(self.apply_workspace_layout)
        dlg.exec_()

    def apply_workspace_layout(self, layout_id: str) -> None:
        """Apply a workspace layout preset and undock plots that no longer fit."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        extras = mgr.apply_layout(layout_id, preserve_plots=True)
        for w in extras:
            self._float_released_plot_widget(w)
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self.status_label.setText(f"Layout: {layout_id.replace('_', ' ')}.")

    def _on_processes_dialog_destroyed(self) -> None:
        self._processes_dialog = None

    def open_processes_dialog(self) -> None:
        from ..processes_dialog import ProcessesDialog

        dlg = getattr(self, "_processes_dialog", None)
        if dlg is not None:
            try:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                dlg._reload()
                return
            except RuntimeError:
                self._processes_dialog = None
        w = ProcessesDialog(self)
        self._processes_dialog = w
        w.destroyed.connect(self._on_processes_dialog_destroyed)
        w.show()
