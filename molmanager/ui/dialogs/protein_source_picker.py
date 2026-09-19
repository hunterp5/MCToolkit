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

"""Manager vs file structure picker for Protein Viewer prepare tools."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QWidget,
)

from ...protein.structure_components import sniff_structure_format, viewer_format_for

_PREPARE_SOURCE_FMTS = frozenset({"pdb", "pqr", "cif"})
_PREPARE_SOURCE_FILTER = (
    "Structures (*.pdb *.ent *.cif *.mmcif *.mcif *.pqr);;"
    "PDB (*.pdb *.ent);;"
    "mmCIF (*.cif *.mmcif *.mcif);;"
    "PQR (*.pqr);;"
    "All files (*.*)"
)


def _browse_path_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(edit, 1)
    btn = QPushButton("Browse…")
    btn.setFixedWidth(76)
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    wrap = QWidget()
    wrap.setLayout(row)
    return wrap


def chain_ids_from_structure_text(text: str, fmt: str) -> tuple[str, ...]:
    """Unique chain IDs in a PDB/mmCIF string."""
    from ...protein.structure_components import parse_structure_components

    seen: list[str] = []
    try:
        comps = parse_structure_components(text or "", fmt or "pdb")
    except Exception:
        return ()
    for spec in comps:
        chain = (spec.chain or "").strip()
        if chain and chain not in seen:
            seen.append(chain)
    return tuple(seen)


def ligand_options_from_structure_text(
    text: str, fmt: str
) -> list[tuple[str, tuple[str, str, str], bool, str]]:
    """Ligand combo rows parsed from a PDB/mmCIF string."""
    from ...protein.structure_components import parse_structure_components

    try:
        comps = parse_structure_components(text or "", fmt or "pdb")
    except Exception:
        return []
    out: list[tuple[str, tuple[str, str, str], bool, str]] = []
    for spec in comps:
        if spec.kind != "ligand":
            continue
        key = (spec.chain or "", str(spec.resi or "").strip() or "0", spec.icode or "")
        label = spec.label or f"{spec.resn} {spec.chain}{spec.resi}"
        out.append((label, key, False, ""))
    return out


class ProteinStructureSourceMixin:
    """True mixin: add Manager / file radios to a prepare dialog's Structure group."""

    _source_output_tag = "prepared"
    _source_tmp_prefix = "molmanager_prepare_in_"
    _source_tool_title = "Prepare"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def _add_structure_source_rows(self, form: QFormLayout) -> None:
        self.radio_src_manager = QRadioButton("Manager")
        self.radio_src_manager.setToolTip(
            "Use a structure already loaded in the Protein Viewer Manager."
        )
        self.radio_src_file = QRadioButton("File…")
        self.radio_src_file.setToolTip(
            "Read a PDB or mmCIF from disk without loading it into the Manager first."
        )
        self.radio_src_manager.setChecked(True)
        src_group = QButtonGroup(self)
        src_group.addButton(self.radio_src_manager)
        src_group.addButton(self.radio_src_file)
        src_row = QWidget()
        src_l = QHBoxLayout(src_row)
        src_l.setContentsMargins(0, 0, 0, 0)
        src_l.setSpacing(12)
        src_l.addWidget(self.radio_src_manager)
        src_l.addWidget(self.radio_src_file)
        src_l.addStretch()
        form.addRow("Source:", src_row)
        self.combo_src_manager = QComboBox()
        self.combo_src_manager.setToolTip("Loaded structures listed in the Manager.")
        form.addRow("Protein:", self.combo_src_manager)
        self.edit_src_file = QLineEdit()
        self.edit_src_file.setPlaceholderText("PDB or mmCIF")
        self.src_file_row = _browse_path_row(self.edit_src_file, self._browse_source_file)
        form.addRow("File:", self.src_file_row)
        self._resolved_source: tuple[str, str, str, Path | None] | None = None
        self.radio_src_manager.toggled.connect(self._on_structure_source_changed)
        self.combo_src_manager.currentIndexChanged.connect(self._on_structure_source_changed)
        self.edit_src_file.editingFinished.connect(self._on_structure_source_changed)

    def _refresh_structure_source(self) -> None:
        viewer = self._viewer
        groups = []
        getter = getattr(viewer, "_manager_groups", None)
        if callable(getter):
            groups = list(getter() or [])
        active_id = ""
        source_id = getattr(viewer, "prepare_source_id", None)
        if callable(source_id):
            active_id = str(source_id() or "")
        self.combo_src_manager.blockSignals(True)
        self.combo_src_manager.clear()
        select = 0
        for i, (sid, name) in enumerate(groups):
            self.combo_src_manager.addItem(str(name), str(sid))
            if str(sid) == active_id:
                select = i
        if groups:
            self.combo_src_manager.setCurrentIndex(select)
        self.combo_src_manager.blockSignals(False)
        self.radio_src_manager.blockSignals(True)
        self.radio_src_file.blockSignals(True)
        if groups:
            self.radio_src_manager.setChecked(True)
        else:
            self.radio_src_file.setChecked(True)
        self.radio_src_manager.blockSignals(False)
        self.radio_src_file.blockSignals(False)
        self._on_structure_source_changed()

    def _sync_structure_source_enabled(self) -> None:
        has_mgr = self.combo_src_manager.count() > 0
        self.radio_src_manager.setEnabled(has_mgr)
        if not has_mgr and self.radio_src_manager.isChecked():
            self.radio_src_file.blockSignals(True)
            self.radio_src_file.setChecked(True)
            self.radio_src_file.blockSignals(False)
        manager = self.radio_src_manager.isChecked() and has_mgr
        self.combo_src_manager.setEnabled(manager)
        self.src_file_row.setEnabled(not manager)

    def _on_structure_source_changed(self, *_args) -> None:
        self._resolved_source = None
        self._sync_structure_source_enabled()
        self._suggest_output_from_source()
        self._apply_structure_source_side_effects()

    def _apply_structure_source_side_effects(self) -> None:
        chk = getattr(self, "chk_keep_selected_waters", None)
        if chk is not None:
            manager = self.radio_src_manager.isChecked()
            chk.setEnabled(manager)
            if not manager:
                chk.setChecked(False)
        refresh_water = getattr(self, "_refresh_water_label", None)
        if callable(refresh_water):
            refresh_water()
        refresh_box = getattr(self, "_refresh_box_ligand_combo", None)
        if callable(refresh_box):
            refresh_box()
        refresh_chains = getattr(self, "_refresh_chain_list", None)
        if callable(refresh_chains):
            refresh_chains()
        refresh_lig = getattr(self, "_refresh_ligand_combo", None)
        if callable(refresh_lig):
            refresh_lig()

    def _chosen_manager_id(self) -> str:
        if not self.radio_src_manager.isChecked():
            return ""
        return str(self.combo_src_manager.currentData() or "")

    def _source_display_path(self) -> tuple[str, Path | None]:
        if self.radio_src_file.isChecked():
            raw = (self.edit_src_file.text() or "").strip()
            if not raw:
                return "", None
            rec = Path(raw).expanduser()
            return rec.name, rec
        getter = getattr(self._viewer, "prepare_source", None)
        if not callable(getter):
            return "", None
        name, _text, _fmt, path = getter(self._chosen_manager_id() or None)
        return name, path

    def _suggest_output_from_source(self) -> None:
        name, path = self._source_display_path()
        if not name and path is None:
            return
        base = path if path is not None else Path(name or "structure")
        tag = getattr(self, "_source_output_tag", "prepared")
        suffix = str(getattr(self, "_source_output_suffix", "") or "").strip()
        if not suffix:
            fmt = "cif"
            combo = getattr(self, "combo_out_fmt", None)
            if combo is not None:
                fmt = combo.currentData() or "cif"
            suffix = ".pdb" if fmt == "pdb" else ".cif"
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        suggested = base.with_name(f"{base.stem}_{tag}{suffix}")
        edit = getattr(self, "edit_out", None)
        if edit is not None:
            edit.setText(str(suggested))

    def _browse_source_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Structure file",
            self.edit_src_file.text().strip(),
            _PREPARE_SOURCE_FILTER,
        )
        if not path:
            return
        self.edit_src_file.setText(path)
        self.radio_src_file.setChecked(True)
        self._on_structure_source_changed()

    def chosen_structure_source(self) -> tuple[str, str, str, Path | None]:
        """Return ``(name, text, fmt, path)`` for the selected Manager item or file."""
        if self.radio_src_file.isChecked():
            raw = (self.edit_src_file.text() or "").strip()
            if not raw:
                return ("", "", "pdb", None)
            rec = Path(raw).expanduser()
            if not rec.is_file():
                raise ValueError(f"Structure file not found:\n{rec}")
            text = rec.read_text(encoding="utf-8")
            fmt = viewer_format_for(sniff_structure_format(rec, text))
            self._resolved_source = (rec.name, text, fmt, rec)
            return self._resolved_source
        getter = getattr(self._viewer, "prepare_source", None)
        if not callable(getter):
            return ("", "", "pdb", None)
        result = getter(self._chosen_manager_id() or None)
        self._resolved_source = result
        return result

    def chosen_chain_ids(self) -> tuple[str, ...]:
        if self.radio_src_manager.isChecked():
            getter = getattr(self._viewer, "prepare_chain_ids", None)
            if callable(getter):
                return tuple(getter(self._chosen_manager_id() or None) or ())
            return ()
        try:
            _name, text, fmt, _path = self.chosen_structure_source()
        except (OSError, ValueError):
            return ()
        return chain_ids_from_structure_text(text, fmt)

    def chosen_water_keys(self) -> tuple[tuple[str, str, str], ...]:
        if not self.radio_src_manager.isChecked():
            return ()
        getter = getattr(self._viewer, "prepare_water_keys", None)
        if not callable(getter):
            return ()
        return tuple(getter(self._chosen_manager_id() or None) or ())

    def chosen_ligand_options(self) -> list[tuple[str, tuple[str, str, str], bool, str]]:
        if self.radio_src_manager.isChecked():
            getter = getattr(self._viewer, "prepare_ligand_options", None)
            if callable(getter):
                return list(getter(self._chosen_manager_id() or None) or [])
            return []
        try:
            _name, text, fmt, _path = self.chosen_structure_source()
        except (OSError, ValueError):
            return []
        return ligand_options_from_structure_text(text, fmt)

    def _write_input_snapshot(self) -> Path:
        if self._resolved_source is None:
            _name, text, fmt, _path = self.chosen_structure_source()
        else:
            _name, text, fmt, _path = self._resolved_source
        fmt = fmt or "pdb"
        title = getattr(self, "_source_tool_title", "Prepare")
        if fmt not in _PREPARE_SOURCE_FMTS:
            raise ValueError(f"{title} supports PDB and mmCIF structures.")
        suffix = ".cif" if fmt == "cif" else ".pdb"
        prefix = getattr(self, "_source_tmp_prefix", "molmanager_prepare_in_")
        tmp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        path = tmp_dir / f"input{suffix}"
        path.write_text(text, encoding="utf-8")
        self._input_tmp = path
        return path
