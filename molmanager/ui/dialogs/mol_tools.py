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

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...fragment_recomposition_filters import (
    parse_recomposition_filter_text,
    recomposition_filter_property_help,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import (
    TOOL_ADD_EXPLICIT_HYDROGENS,
    TOOL_CORE_DECOMP,
    TOOL_REMOVE_EXPLICIT_HYDROGENS,
)
from ...fragment_decomposition import detect_fragment_column_prefixes
from ...workers import (
    ConformerGenParams,
    SuperposeParams,
    SuperposeStructuresParams,
)
from .scope import selection_scope_checked


_RESERVED_DISCONNECT_COLUMNS = frozenset({"ID_HIDDEN"})
_CONFORMER_FORCE_FIELDS = ("MMFF", "MMFF94s", "UFF")
_CONFORMER_FF_TOOLTIP = (
    "MMFF94 or MMFF94s when parameters exist; otherwise falls back to UFF automatically."
)


@dataclass(frozen=True)
class ConformerOutputOptions:
    """Optional destinations for generated conformers beyond the ``confs`` column."""

    add_to_table: bool = False
    save_to_file: bool = False
    save_path: str | None = None


class ConformerOutputOptionsPanel(QWidget):
    """Checkboxes and path picker for table append / SDF export."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.add_to_table_cb = QCheckBox("Add as Entries")
        self.add_to_table_cb.setToolTip(
            "Append each generated conformer as a new table row (Parent OID and Conformer columns)."
        )
        layout.addWidget(self.add_to_table_cb)

        self.save_to_file_cb = QCheckBox("Save to SDF")
        self.save_to_file_cb.setToolTip("Write all generated conformers to an SDF file.")
        self.save_to_file_cb.toggled.connect(self._sync_save_path_enabled)
        layout.addWidget(self.save_to_file_cb)

        path_row = QHBoxLayout()
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("conformers.sdf")
        self.save_path_edit.setEnabled(False)
        path_row.addWidget(self.save_path_edit, 1)
        self.save_browse_btn = QPushButton("Browse…")
        self.save_browse_btn.setEnabled(False)
        self.save_browse_btn.clicked.connect(self._browse_save_path)
        path_row.addWidget(self.save_browse_btn)
        layout.addLayout(path_row)

    def _sync_save_path_enabled(self, enabled: bool) -> None:
        self.save_path_edit.setEnabled(bool(enabled))
        self.save_browse_btn.setEnabled(bool(enabled))

    def _browse_save_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save conformations",
            self.save_path_edit.text() or "conformers.sdf",
            "SDF (*.sdf);;All files (*.*)",
        )
        if path:
            if not path.lower().endswith(".sdf"):
                path = f"{path}.sdf"
            self.save_path_edit.setText(path)

    def options(self) -> ConformerOutputOptions:
        save = bool(self.save_to_file_cb.isChecked())
        path = (self.save_path_edit.text() or "").strip() or None
        return ConformerOutputOptions(
            add_to_table=bool(self.add_to_table_cb.isChecked()),
            save_to_file=save,
            save_path=path if save else None,
        )

    def validate(self, dialog: QDialog) -> bool:
        opts = self.options()
        if opts.save_to_file and not opts.save_path:
            QMessageBox.warning(dialog, dialog.windowTitle(), "Choose an output SDF file path.")
            return False
        return True


def _validate_fragment_output_columns(
    dialog: QDialog,
    *,
    update_target: bool,
    target_column: str,
    largest_name: str,
    smallest_name: str,
) -> bool:
    if not smallest_name:
        QMessageBox.warning(
            dialog, dialog.windowTitle(), "Enter a name for the smallest fragment column."
        )
        return False
    if update_target:
        if smallest_name in _RESERVED_DISCONNECT_COLUMNS:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                f"The smallest fragment column name “{smallest_name}” is reserved.",
            )
            return False
        return True
    if not largest_name:
        QMessageBox.warning(
            dialog, dialog.windowTitle(), "Enter a name for the largest fragment column."
        )
        return False
    if largest_name == smallest_name:
        QMessageBox.warning(
            dialog,
            dialog.windowTitle(),
            "Largest and smallest fragment columns must have different names.",
        )
        return False
    if largest_name == target_column:
        QMessageBox.warning(
            dialog,
            dialog.windowTitle(),
            "Largest fragment column must differ from the target column when using a new column.",
        )
        return False
    for label, name in (("Largest fragment", largest_name), ("Smallest fragment", smallest_name)):
        if name in _RESERVED_DISCONNECT_COLUMNS:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                f"The {label} column name “{name}” is reserved.",
            )
            return False
    return True


class DisconnectFragmentsDialog(QDialog):
    """Pick the target structure field; update it by default or write results to new columns."""

    def __init__(
        self,
        source_labels: list[str],
        existing_headers: list[str],
        selected_row_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Disconnect Largest Fragments")
        self._existing = list(existing_headers)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        form = QFormLayout()
        form.setVerticalSpacing(4)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        form.addRow("Target column:", self.src_combo)

        self.radio_update_target = QRadioButton("Update Target Column")
        self.radio_new_columns = QRadioButton("New Column")
        self.radio_update_target.setChecked(True)
        form.addRow(self.radio_update_target)
        form.addRow(self.radio_new_columns)

        self.largest_edit = QLineEdit("Largest fragment SMILES")
        form.addRow("Largest Fragment:", self.largest_edit)
        self.fragments_edit = QLineEdit("Fragments")
        form.addRow("Smallest Fragment:", self.fragments_edit)
        root.addLayout(form)

        self.radio_update_target.toggled.connect(self._sync_output_fields)
        self.radio_new_columns.toggled.connect(self._sync_output_fields)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        root.addWidget(self.no_render_2d_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._sync_output_fields()
        self.adjustSize()
        make_window_minimizable(self)

    def _sync_output_fields(self) -> None:
        new_only = self.radio_new_columns.isChecked()
        self.largest_edit.setEnabled(new_only)

    def _try_accept(self) -> None:
        update_target = self.radio_update_target.isChecked()
        largest = (self.largest_edit.text() or "").strip()
        smallest = (self.fragments_edit.text() or "").strip()
        if not _validate_fragment_output_columns(
            self,
            update_target=update_target,
            target_column=self.src_combo.currentText(),
            largest_name=largest,
            smallest_name=smallest,
        ):
            return
        self.accept()

    def config(self) -> tuple[str, bool, str | None, str, bool, bool]:
        """
        Returns ``(target_column, update_target, largest_column_or_None, smaller_fragments_column,
        only_selected_rows, no_render_2d)``.

        When *update_target* is true, the largest fragment is written to the target column and
        *largest_column_or_None* is ``None``. Otherwise results go to the named largest column.
        """
        src = self.src_combo.currentText()
        update_target = self.radio_update_target.isChecked()
        largest = None if update_target else (self.largest_edit.text() or "").strip()
        fragments = (self.fragments_edit.text() or "").strip()
        only_sel = selection_scope_checked(self)
        no_render = self.no_render_2d_cb.isChecked()
        return src, update_target, largest, fragments, only_sel, no_render


class FastPrepareDialog(QDialog):
    """Disconnect largest fragment, optionally neutralize, then render 2D in one pipeline."""

    def __init__(
        self,
        source_labels: list[str],
        existing_headers: list[str],
        selected_row_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Fast Prepare")
        self._existing = list(existing_headers)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        form = QFormLayout()
        form.setVerticalSpacing(4)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        form.addRow("Target column:", self.src_combo)

        self.radio_update_target = QRadioButton("Update Target Column")
        self.radio_new_columns = QRadioButton("New Column")
        self.radio_update_target.setChecked(True)
        form.addRow(self.radio_update_target)
        form.addRow(self.radio_new_columns)

        self.largest_edit = QLineEdit("Largest fragment SMILES")
        form.addRow("Largest Fragment:", self.largest_edit)
        self.fragments_edit = QLineEdit("Fragments")
        form.addRow("Smallest Fragment:", self.fragments_edit)
        root.addLayout(form)

        self.radio_update_target.toggled.connect(self._sync_output_fields)
        self.radio_new_columns.toggled.connect(self._sync_output_fields)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        self.neutralize_cb = QCheckBox("Neutralize")
        self.neutralize_cb.setChecked(False)
        self.neutralize_cb.setToolTip(
            "After keeping the largest fragment, zero net formal charge with RDKit Uncharger. "
            "Leave off to keep the fragment charges as-is."
        )
        root.addWidget(self.neutralize_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._sync_output_fields()
        self.adjustSize()
        make_window_minimizable(self)

    def _sync_output_fields(self) -> None:
        self.largest_edit.setEnabled(self.radio_new_columns.isChecked())

    def _try_accept(self) -> None:
        update_target = self.radio_update_target.isChecked()
        largest = (self.largest_edit.text() or "").strip()
        smallest = (self.fragments_edit.text() or "").strip()
        if not _validate_fragment_output_columns(
            self,
            update_target=update_target,
            target_column=self.src_combo.currentText(),
            largest_name=largest,
            smallest_name=smallest,
        ):
            return
        self.accept()

    def config(self) -> tuple[str, bool, str | None, str, bool, bool]:
        """
        Returns ``(target_column, update_target, largest_column_or_None, smallest_fragments_column,
        only_selected_rows, neutralize)``.
        """
        update_target = self.radio_update_target.isChecked()
        return (
            self.src_combo.currentText(),
            update_target,
            None if update_target else (self.largest_edit.text() or "").strip(),
            (self.fragments_edit.text() or "").strip(),
            selection_scope_checked(self),
            bool(self.neutralize_cb.isChecked()),
        )


class NeutralizeDialog(QDialog):
    """Neutralize structures in a chosen column (net formal charge → 0)."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neutralize")
        self.resize(420, 140)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        f = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        f.addRow("Target column:", self.src_combo)
        root.addLayout(f)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after neutralization.")
        root.addWidget(self.no_render_2d_cb)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )


class AddExplicitHydrogensDialog(QDialog):
    """Add explicit hydrogen atoms to structures in a chosen column."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_ADD_EXPLICIT_HYDROGENS)
        self.resize(420, 140)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        f = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        f.addRow("Target column:", self.src_combo)
        root.addLayout(f)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after adding hydrogens.")
        root.addWidget(self.no_render_2d_cb)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )


class RemoveExplicitHydrogensDialog(QDialog):
    """Remove explicit hydrogen atoms from structures in a chosen column."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_REMOVE_EXPLICIT_HYDROGENS)
        self.resize(420, 140)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        f = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        f.addRow("Target column:", self.src_combo)
        root.addLayout(f)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after removing hydrogens.")
        root.addWidget(self.no_render_2d_cb)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )


class ConformerEmbedAdvancedPanel(QWidget):
    """Optional ETKDG / hydrogen knobs. Unchecked uses built-in defaults."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.advanced_cb = QCheckBox("Advanced")
        self.advanced_cb.setChecked(False)
        self.advanced_cb.setToolTip(
            "ETKDG embedder flags and hydrogen handling. Leave off to use MolManager defaults."
        )
        root.addWidget(self.advanced_cb)

        self._box = QGroupBox(self)
        self._box.setTitle("")
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)

        self.enforce_chirality_cb = QCheckBox("Enforce chirality")
        self.enforce_chirality_cb.setChecked(True)
        self.enforce_chirality_cb.setToolTip(
            "Preserve specified stereochemistry during ETKDG embedding."
        )
        form.addRow(self.enforce_chirality_cb)

        self.random_coords_cb = QCheckBox("Use random coordinates")
        self.random_coords_cb.setChecked(False)
        self.random_coords_cb.setToolTip(
            "Start from random coords instead of distance-geometry embedding. "
            "Can help stubborn rings, usually slower and noisier."
        )
        form.addRow(self.random_coords_cb)

        self.exp_torsions_cb = QCheckBox("Experimental torsion preferences")
        self.exp_torsions_cb.setChecked(True)
        self.exp_torsions_cb.setToolTip(
            "Use ETKDG experimental torsion-angle preferences (recommended)."
        )
        form.addRow(self.exp_torsions_cb)

        self.small_ring_cb = QCheckBox("Small-ring torsions")
        self.small_ring_cb.setChecked(True)
        self.small_ring_cb.setToolTip("ETKDG small-ring torsion corrections.")
        form.addRow(self.small_ring_cb)

        self.macrocycle_cb = QCheckBox("Macrocycle torsions")
        self.macrocycle_cb.setChecked(True)
        self.macrocycle_cb.setToolTip("ETKDG macrocycle torsion corrections.")
        form.addRow(self.macrocycle_cb)

        self.basic_knowledge_cb = QCheckBox("Basic knowledge terms")
        self.basic_knowledge_cb.setChecked(True)
        self.basic_knowledge_cb.setToolTip("ETKDG basic-knowledge terms (planar aromatics, etc.).")
        form.addRow(self.basic_knowledge_cb)

        self.heavy_rms_cb = QCheckBox("Heavy atoms only for RMS")
        self.heavy_rms_cb.setChecked(True)
        self.heavy_rms_cb.setToolTip(
            "Embed RMS prune and post-minimize RMS prune ignore hydrogens."
        )
        form.addRow(self.heavy_rms_cb)

        self.keep_hs_cb = QCheckBox("Keep explicit hydrogens")
        self.keep_hs_cb.setChecked(False)
        self.keep_hs_cb.setToolTip(
            "Leave hydrogens on after minimization (useful for some docking exports)."
        )
        form.addRow(self.keep_hs_cb)

        self.max_embed_sb = QSpinBox()
        self.max_embed_sb.setRange(0, 2000)
        self.max_embed_sb.setValue(0)
        self.max_embed_sb.setSpecialValueText("0 = ETKDG default")
        self.max_embed_sb.setToolTip(
            "Max embedding attempts per conformer (ETKDG maxIterations). "
            "0 leaves the RDKit default (typically 10 × number of atoms)."
        )
        form.addRow("Max embed attempts:", self.max_embed_sb)

        box_layout = QVBoxLayout(self._box)
        box_layout.setContentsMargins(8, 8, 8, 8)
        box_layout.addWidget(inner)
        root.addWidget(self._box)
        self.advanced_cb.toggled.connect(self._on_toggled)
        self._on_toggled(False)

    def isChecked(self) -> bool:
        return bool(self.advanced_cb.isChecked())

    def setChecked(self, on: bool) -> None:
        self.advanced_cb.setChecked(bool(on))

    def _on_toggled(self, on: bool) -> None:
        self._box.setVisible(bool(on))
        win = self.window()
        if win is not None:
            win.adjustSize()

    def values(self) -> dict:
        """Advanced fields to merge into :class:`ConformerGenParams`."""
        if not self.isChecked():
            return {}
        return {
            "enforce_chirality": bool(self.enforce_chirality_cb.isChecked()),
            "use_random_coords": bool(self.random_coords_cb.isChecked()),
            "use_exp_torsion_prefs": bool(self.exp_torsions_cb.isChecked()),
            "use_small_ring_torsions": bool(self.small_ring_cb.isChecked()),
            "use_macrocycle_torsions": bool(self.macrocycle_cb.isChecked()),
            "use_basic_knowledge": bool(self.basic_knowledge_cb.isChecked()),
            "only_heavy_atoms_for_rms": bool(self.heavy_rms_cb.isChecked()),
            "max_embed_attempts": int(self.max_embed_sb.value()),
            "keep_hydrogens": bool(self.keep_hs_cb.isChecked()),
        }


class GenerateConformationsDialog(QDialog):
    """Configure ETKDG embedding, minimizer, energy window, optional alignment, and table scope."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Conformations")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(6)
        self.num_confs_sb = QSpinBox()
        self.num_confs_sb.setRange(1, 500)
        self.num_confs_sb.setValue(25)
        self.num_confs_sb.setToolTip(
            "Number of conformers to embed before minimization and pruning."
        )
        form.addRow("Conformers:", self.num_confs_sb)

        self.energy_win_sb = QDoubleSpinBox()
        self.energy_win_sb.setRange(0.0, 200.0)
        self.energy_win_sb.setDecimals(2)
        self.energy_win_sb.setSingleStep(1.0)
        self.energy_win_sb.setValue(10.0)
        self.energy_win_sb.setSuffix(" kcal/mol")
        self.energy_win_sb.setSpecialValueText("0 = keep all (no window)")
        self.energy_win_sb.setToolTip(
            "Keep only conformers within this energy above the lowest-energy conformer. "
            "Set to 0 to skip energy pruning."
        )
        form.addRow("Energy window:", self.energy_win_sb)

        self.ff_combo = QComboBox()
        self.ff_combo.addItems(list(_CONFORMER_FORCE_FIELDS))
        self.ff_combo.setToolTip(_CONFORMER_FF_TOOLTIP)
        form.addRow("Force field:", self.ff_combo)

        self.seed_sb = QSpinBox()
        self.seed_sb.setRange(0, 2_147_483_647)
        self.seed_sb.setValue(0xC0FFEE)
        self.seed_sb.setToolTip("Random seed passed to the ETKDG embedder.")
        form.addRow("Seed:", self.seed_sb)

        self.prune_rms_sb = QDoubleSpinBox()
        self.prune_rms_sb.setRange(-1.0, 3.0)
        self.prune_rms_sb.setDecimals(3)
        self.prune_rms_sb.setSingleStep(0.05)
        self.prune_rms_sb.setValue(-1.0)
        self.prune_rms_sb.setSpecialValueText("default (ETKDG)")
        self.prune_rms_sb.setToolTip(
            "ETKDG pruneRmsThresh during embed; −1 uses the parameter object default."
        )
        form.addRow("RMS prune (embed):", self.prune_rms_sb)

        self.post_min_rms_sb = QDoubleSpinBox()
        self.post_min_rms_sb.setRange(0.0, 3.0)
        self.post_min_rms_sb.setDecimals(3)
        self.post_min_rms_sb.setSingleStep(0.05)
        self.post_min_rms_sb.setValue(0.0)
        self.post_min_rms_sb.setSpecialValueText("0 = off")
        self.post_min_rms_sb.setToolTip(
            "After minimization, drop higher-energy conformers within this heavy-atom RMS "
            "of a kept pose. 0 skips this extra prune."
        )
        form.addRow("RMS prune (post-min):", self.post_min_rms_sb)

        self.max_keep_sb = QSpinBox()
        self.max_keep_sb.setRange(0, 500)
        self.max_keep_sb.setValue(0)
        self.max_keep_sb.setSpecialValueText("0 = no extra cap")
        self.max_keep_sb.setToolTip(
            "Keep at most this many lowest-energy conformers after energy-window and RMS "
            "pruning. 0 keeps all survivors."
        )
        form.addRow("Max keep:", self.max_keep_sb)

        self.max_iters_sb = QSpinBox()
        self.max_iters_sb.setRange(20, 2000)
        self.max_iters_sb.setValue(200)
        self.max_iters_sb.setToolTip("Maximum minimizer iterations per conformer.")
        form.addRow("Max iterations:", self.max_iters_sb)

        self.align_pat_edit = QLineEdit()
        self.align_pat_edit.setPlaceholderText("optional SMILES/SMARTS")
        self.align_pat_edit.setToolTip(
            "If set, generated conformers are rigidly aligned on atoms that match this query "
            "(same graph as the molecule). Leave empty to keep the embedder orientations."
        )
        self.align_smarts_cb = QCheckBox("SMARTS")
        self.align_smarts_cb.setChecked(False)
        self.align_smarts_cb.setToolTip("Parse the pattern as SMARTS instead of SMILES.")
        pat_row = QHBoxLayout()
        pat_row.setContentsMargins(0, 0, 0, 0)
        pat_row.setSpacing(6)
        pat_row.addWidget(self.align_pat_edit, 1)
        pat_row.addWidget(self.align_smarts_cb)
        form.addRow("Align on:", pat_row)

        root.addLayout(form)

        self.advanced_panel = ConformerEmbedAdvancedPanel(self)
        root.addWidget(self.advanced_panel)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        self.output_panel = ConformerOutputOptionsPanel(self)
        root.addWidget(self.output_panel)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _try_accept(self) -> None:
        if not self.output_panel.validate(self):
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def output_options(self) -> ConformerOutputOptions:
        return self.output_panel.options()

    def params(self) -> ConformerGenParams:
        return ConformerGenParams(
            num_confs=int(self.num_confs_sb.value()),
            energy_window_kcal=float(self.energy_win_sb.value()),
            force_field=str(self.ff_combo.currentText()),
            random_seed=int(self.seed_sb.value()),
            prune_rms_threshold=float(self.prune_rms_sb.value()),
            max_iterations=int(self.max_iters_sb.value()),
            align_pattern=(self.align_pat_edit.text() or "").strip(),
            align_pattern_is_smarts=bool(self.align_smarts_cb.isChecked()),
            post_min_rms_threshold=float(self.post_min_rms_sb.value()),
            max_keep=int(self.max_keep_sb.value()),
            **self.advanced_panel.values(),
        )


class SuperposeConformersDialog(QDialog):
    """Configure rigid superposition of conformers read from packed ``confs`` cells."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Superpose Conformers")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        self.ref_sb = QSpinBox()
        self.ref_sb.setRange(0, 499)
        self.ref_sb.setValue(0)
        self.ref_sb.setToolTip(
            "0-based index into the conformer list for each row (sorted by RDKit conformer id). "
            "If a row has fewer conformers than this index, the last conformer is used as reference."
        )
        form.addRow("Reference index:", self.ref_sb)

        self.heavy_cb = QCheckBox("Heavy atoms only")
        self.heavy_cb.setChecked(True)
        self.heavy_cb.setToolTip(
            "Alignment minimizes RMS over non-hydrogen atoms only (recommended for noisy H positions)."
        )
        form.addRow(self.heavy_cb)

        self.reflect_cb = QCheckBox("Allow reflection")
        self.reflect_cb.setChecked(False)
        self.reflect_cb.setToolTip(
            "If checked, the alignment may invert chirality-related rigid transforms; leave off for typical conformers."
        )
        form.addRow(self.reflect_cb)

        self.max_align_sb = QSpinBox()
        self.max_align_sb.setRange(10, 500)
        self.max_align_sb.setValue(50)
        self.max_align_sb.setToolTip(
            "Maximum iterations passed to the RDKit alignment optimizer per conformer pair."
        )
        form.addRow("Max iterations:", self.max_align_sb)

        self.align_pat_edit = QLineEdit()
        self.align_pat_edit.setPlaceholderText("optional SMILES/SMARTS")
        self.align_pat_edit.setToolTip(
            "If set, rigid alignment uses only atoms that match this query on each conformer "
            "(same graph as the row molecule). Leave empty to align on all heavy atoms or all atoms."
        )
        self.align_smarts_cb = QCheckBox("SMARTS")
        self.align_smarts_cb.setChecked(False)
        self.align_smarts_cb.setToolTip("Parse the pattern as SMARTS instead of SMILES.")
        pat_row = QHBoxLayout()
        pat_row.setContentsMargins(0, 0, 0, 0)
        pat_row.setSpacing(6)
        pat_row.addWidget(self.align_pat_edit, 1)
        pat_row.addWidget(self.align_smarts_cb)
        form.addRow("Align on:", pat_row)
        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SuperposeParams:
        return SuperposeParams(
            reference_conformer_index=int(self.ref_sb.value()),
            heavy_atoms_only=bool(self.heavy_cb.isChecked()),
            reflect=bool(self.reflect_cb.isChecked()),
            max_align_iters=int(self.max_align_sb.value()),
            align_pattern=(self.align_pat_edit.text() or "").strip(),
            align_pattern_is_smarts=bool(self.align_smarts_cb.isChecked()),
        )


class SuperposeStructuresDialog(QDialog):
    """Align selected table structures onto a reference (MCS / pattern / best-effort O3A)."""

    def __init__(
        self,
        selected_row_count: int = 0,
        *,
        source_columns: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Superpose Structures")
        self.setMinimumWidth(440)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0
        sources = [c for c in (source_columns or ["Structure"]) if c]
        if not sources:
            sources = ["Structure"]

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)

        self.src_combo = QComboBox()
        self.src_combo.addItems(sources)
        self.src_combo.setToolTip(
            "Where to read 3D coordinates. Prefer confs when present; Structure uses the "
            "in-memory molecule (embeds a 3D conformer if needed)."
        )
        form.addRow("Source:", self.src_combo)

        self.heavy_cb = QCheckBox("Heavy atoms only")
        self.heavy_cb.setChecked(True)
        self.heavy_cb.setToolTip(
            "When aligning on a substructure or MCS, use non-hydrogen atoms only."
        )
        form.addRow(self.heavy_cb)

        self.reflect_cb = QCheckBox("Allow reflection")
        self.reflect_cb.setChecked(False)
        self.reflect_cb.setToolTip(
            "If checked, rigid AlignMol may use a reflected pose; leave off to preserve chirality."
        )
        form.addRow(self.reflect_cb)

        self.max_align_sb = QSpinBox()
        self.max_align_sb.setRange(10, 500)
        self.max_align_sb.setValue(50)
        self.max_align_sb.setToolTip(
            "Maximum iterations for RDKit AlignMol when an atom map is used."
        )
        form.addRow("Max iterations:", self.max_align_sb)

        self.align_pat_edit = QLineEdit()
        self.align_pat_edit.setPlaceholderText("optional SMILES/SMARTS")
        self.align_pat_edit.setToolTip(
            "If set, align on this common substructure when it matches both the reference and "
            "the probe. If it does not match, MCS / best-effort overlay is used instead."
        )
        self.align_smarts_cb = QCheckBox("SMARTS")
        self.align_smarts_cb.setChecked(False)
        self.align_smarts_cb.setToolTip("Parse the pattern as SMARTS instead of SMILES.")
        pat_row = QHBoxLayout()
        pat_row.setContentsMargins(0, 0, 0, 0)
        pat_row.setSpacing(6)
        pat_row.addWidget(self.align_pat_edit, 1)
        pat_row.addWidget(self.align_smarts_cb)
        form.addRow("Align on:", pat_row)

        self.mcs_cb = QCheckBox("Use MCS when no pattern match")
        self.mcs_cb.setChecked(True)
        self.mcs_cb.setToolTip(
            "Find a maximum common substructure between each probe and the reference. "
            "If that also fails, overlay with Crippen / MMFF O3A (best effort)."
        )
        form.addRow(self.mcs_cb)
        root.addLayout(form)

        tip = QLabel(
            "Reference = first row in scope (table order). The aligned ensemble is stored on the "
            "reference row’s <b>superpose</b> column and opened in a 3D results window "
            "(energies, ΔE, population, and RMSD when topologies match)."
        )
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.RichText)
        root.addWidget(tip)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setChecked(True)
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def source_column(self) -> str:
        return str(self.src_combo.currentText() or "Structure")

    def params(self) -> SuperposeStructuresParams:
        return SuperposeStructuresParams(
            heavy_atoms_only=bool(self.heavy_cb.isChecked()),
            reflect=bool(self.reflect_cb.isChecked()),
            max_align_iters=int(self.max_align_sb.value()),
            align_pattern=(self.align_pat_edit.text() or "").strip(),
            align_pattern_is_smarts=bool(self.align_smarts_cb.isChecked()),
            use_mcs=bool(self.mcs_cb.isChecked()),
        )


@dataclass(frozen=True)
class FragmentDecompDialogParams:
    """Arguments from :class:`FragmentDecompositionDialog` for the worker."""

    structure_source: str
    column_prefix: str
    method: str  # "brics" | "recap"
    tool_title: str
    render_2d: bool


class FragmentDecompositionDialog(QDialog):
    """Structure source, column prefix, and scope for BRICS or RECAP decomposition."""

    def __init__(
        self,
        *,
        window_title: str,
        default_prefix: str,
        method: str,
        structure_sources: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self._method = method
        self._tool_title = window_title
        self.setWindowTitle(window_title)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText(default_prefix)
        self.prefix_edit.setToolTip(
            "New columns are named PREFIX_1, PREFIX_2, … (one per fragment)."
        )
        form.addRow("Column name prefix:", self.prefix_edit)
        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        self.render_2d_cb = QCheckBox("Render 2D after decomposition")
        self.render_2d_cb.setChecked(False)
        self.render_2d_cb.setToolTip(
            "Render the new fragment columns as 2D depictions (pixmap-only) after decomposition finishes."
        )
        root.addWidget(self.render_2d_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> FragmentDecompDialogParams:
        return FragmentDecompDialogParams(
            structure_source=self.src_combo.currentText(),
            column_prefix=(self.prefix_edit.text() or "").strip(),
            method=self._method,
            tool_title=self._tool_title,
            render_2d=bool(self.render_2d_cb.isChecked()),
        )


@dataclass(frozen=True)
class FragmentRecompDialogParams:
    """Arguments from :class:`FragmentRecompositionDialog` for the worker."""

    column_prefix: str
    method: str  # "brics" | "recap"
    max_depth: int
    max_products: int
    output_filters: str
    tool_title: str


class FragmentRecompositionDialog(QDialog):
    """Pool fragment SMILES columns and run BRICS or RECAP recomposition."""

    def __init__(
        self,
        *,
        window_title: str,
        default_prefix: str,
        method: str,
        table_headers: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self._method = method
        self._tool_title = window_title
        self._table_headers = list(table_headers)
        self.setWindowTitle(window_title)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.prefix_combo = QComboBox()
        self.prefix_combo.setEditable(True)
        prefixes = detect_fragment_column_prefixes(self._table_headers)
        if default_prefix not in prefixes:
            prefixes = [default_prefix] + prefixes
        self.prefix_combo.addItems(prefixes)
        self.prefix_combo.setCurrentText(default_prefix)
        self.prefix_combo.setToolTip(
            "Use fragment columns from decomposition (e.g. BRICS_1, BRICS_2 or RECAP_1, …)."
        )
        form.addRow("Fragment column prefix:", self.prefix_combo)

        self.max_depth_sb = QSpinBox()
        self.max_depth_sb.setRange(1, 8)
        self.max_depth_sb.setValue(3)
        self.max_depth_sb.setToolTip("Maximum BRICS coupling depth when assembling products.")
        form.addRow("Max coupling depth:", self.max_depth_sb)

        self.max_products_sb = QSpinBox()
        from ...config import load_config

        max_prod_cap = int(load_config().memory_guard_enum_max_products)
        self.max_products_sb.setRange(10, max_prod_cap)
        self.max_products_sb.setValue(min(2000, max_prod_cap))
        self.max_products_sb.setToolTip(
            "Stop after this many accepted product SMILES that meet generation constraints."
        )
        form.addRow("Max products:", self.max_products_sb)
        root.addLayout(form)

        filters_box = QGroupBox("Generation constraints")
        filters_lyt = QVBoxLayout(filters_box)
        self.output_filters_edit = QPlainTextEdit()
        self.output_filters_edit.setPlaceholderText(
            "Optional. Comma- or line-separated AND conditions, e.g.\n"
            "MW 200-500, LogP <= 5, HeavyAtoms >= 10, TPSA < 140"
        )
        self.output_filters_edit.setToolTip(
            "Only assemble products that satisfy these property limits. "
            "Candidates that fail a constraint are skipped and do not count toward max products. "
            f"Supported properties include {recomposition_filter_property_help()}."
        )
        self.output_filters_edit.setMaximumHeight(88)
        filters_lyt.addWidget(self.output_filters_edit)
        root.addWidget(filters_box)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not (self.prefix_combo.currentText() or "").strip():
            QMessageBox.warning(self, self.windowTitle(), "Enter a fragment column prefix.")
            return
        filter_text = self.output_filters_edit.toPlainText().strip()
        if filter_text:
            try:
                parse_recomposition_filter_text(filter_text)
            except ValueError as exc:
                QMessageBox.warning(self, self.windowTitle(), str(exc))
                return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> FragmentRecompDialogParams:
        return FragmentRecompDialogParams(
            column_prefix=(self.prefix_combo.currentText() or "").strip(),
            method=self._method,
            max_depth=int(self.max_depth_sb.value()),
            max_products=int(self.max_products_sb.value()),
            output_filters=self.output_filters_edit.toPlainText().strip(),
            tool_title=self._tool_title,
        )


@dataclass(frozen=True)
class CoreBasedDecompDialogParams:
    """Arguments from :class:`CoreBasedDecompositionDialog` for the worker."""

    core_query: str
    structure_source: str
    column_prefix: str
    only_match_at_r_groups: bool
    remove_hydrogens_post_match: bool
    matching: str  # "greedy" or "exhaustive"


class CoreBasedDecompositionDialog(QDialog):
    """Core SMARTS/SMILES, structure column, RDKit core-based decomposition options."""

    def __init__(self, structure_sources: list[str], selected_row_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_CORE_DECOMP)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("e.g. c1ccc([*:1])cc1 or SMARTS with dummy labels")
        self.core_edit.setToolTip(
            "Parsed as SMARTS first, then as SMILES. Use RDKit-style dummy atoms on the core "
            "that map to substituents in the row molecules."
        )
        form.addRow("Core (SMARTS or SMILES):", self.core_edit)

        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText("RGD")
        self.prefix_edit.setToolTip("New columns are named PREFIX_Core, PREFIX_R1, â€¦")
        form.addRow("Column name prefix:", self.prefix_edit)

        self.only_rg_cb = QCheckBox("Only match at R-groups (onlyMatchAtRGroups)")
        self.only_rg_cb.setChecked(True)
        form.addRow(self.only_rg_cb)

        self.remove_h_cb = QCheckBox("Remove hydrogens after match (removeHydrogensPostMatch)")
        self.remove_h_cb.setChecked(True)
        form.addRow(self.remove_h_cb)

        self.match_combo = QComboBox()
        self.match_combo.addItems(["Greedy", "Exhaustive"])
        self.match_combo.setToolTip("Greedy is faster; Exhaustive explores more matchings.")
        form.addRow("Matching strategy:", self.match_combo)

        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not (self.core_edit.text() or "").strip():
            QMessageBox.warning(self, TOOL_CORE_DECOMP, "Enter a core SMARTS or SMILES.")
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> CoreBasedDecompDialogParams:
        strat = self.match_combo.currentText().strip().lower()
        return CoreBasedDecompDialogParams(
            core_query=(self.core_edit.text() or "").strip(),
            structure_source=self.src_combo.currentText(),
            column_prefix=(self.prefix_edit.text() or "").strip() or "RGD",
            only_match_at_r_groups=bool(self.only_rg_cb.isChecked()),
            remove_hydrogens_post_match=bool(self.remove_h_cb.isChecked()),
            matching="exhaustive" if strat.startswith("exhaustive") else "greedy",
        )
