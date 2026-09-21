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

"""PubChem querying and medchem summary via PubChemPy."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...sources.pubchem_names import names_from_title_and_synonyms
from ...chem.molecule_conversion import morgan_tanimoto_to_query
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..strings import COLUMN_TANIMOTO_SIMILARITY
from ..threadpool_access import start_runnable_on_app_pool

FIELD_COMMON_NAME = "Common Name"
FIELD_SYNONYMS = "Synonyms"


@dataclass(frozen=True)
class PubChemResult:
    cid: int | None
    smiles: str
    fields: dict[str, str]


def pubchem_hit_passes_tanimoto_threshold(tc: float | None, min_t: float) -> bool:
    """Client-side filter: PubChem PUG Threshold can still return sub-threshold hits."""
    return tc is not None and tc + 1e-9 >= float(min_t)


def _pubchem_similarity_sort_key(res: PubChemResult) -> float:
    try:
        return float(res.fields.get(COLUMN_TANIMOTO_SIMILARITY, "") or 0.0)
    except Exception:
        return -1.0


def _get_pubchem_compound_by_smiles(smiles: str):
    try:
        import pubchempy as pcp
    except Exception as e:
        raise RuntimeError("PubChemPy is required. Install requirements.txt.") from e

    comps = pcp.get_compounds(smiles, namespace="smiles")
    return comps[0] if comps else None


def _compound_table_smiles(comp, fallback: str) -> str:
    """Connectivity or isomeric SMILES from a PubChemPy ``Compound``, else ``fallback``."""
    for attr in ("connectivity_smiles", "smiles"):
        v = getattr(comp, attr, None)
        if v:
            t = str(v).strip()
            if t:
                return t
    return (fallback or "").strip()


class _QuerySignals(QObject):
    progress = Signal(int, int, str)  # done, total, current_smiles
    finished = Signal(list, list)  # results, logs (strings)


class _PubChemBatchWorker(QRunnable):
    def __init__(
        self,
        smiles_list: list[str],
        *,
        selected_fields: list[str],
        similarity: tuple[float, int] | None = None,
    ):
        super().__init__()
        self.smiles_list = smiles_list
        self.selected_fields = selected_fields
        self.similarity = similarity  # (min_tanimoto 0–1, max_hits) or None for identity lookup
        self.signals = _QuerySignals()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            import pubchempy as pcp
        except Exception as e:
            self.signals.finished.emit([], [f"ERROR: {e}"])
            return

        results: list[PubChemResult] = []
        logs: list[str] = []

        if self.similarity is not None:
            min_t, max_hits = self.similarity
            q = (self.smiles_list[0] if self.smiles_list else "").strip()
            total = 1
            done = 0
            if self._cancel:
                self.signals.finished.emit([], ["Cancelled by user."])
                return
            done += 1
            self.signals.progress.emit(done, total, q)
            thresh = max(1, min(100, int(round(float(min_t) * 100))))
            max_hits = max(1, min(500, int(max_hits)))
            try:
                comps = pcp.get_compounds(
                    q,
                    namespace="smiles",
                    searchtype="similarity",
                    Threshold=thresh,
                    MaxRecords=max_hits,
                )
            except Exception as e:
                logs.append(f"{q} | similarity ERROR: {e}")
                self.signals.finished.emit(results, logs)
                return
            comps = comps or []
            logs.append(
                f"Similarity 2D (PubChem PUG): query={q!r}  min_Tanimoto≈{min_t:.2f}  "
                f"Threshold={thresh}/100  max_records={max_hits}  hits={len(comps)}"
            )
            for comp in comps:
                if self._cancel:
                    logs.append("Cancelled by user.")
                    break
                row_smi = _compound_table_smiles(comp, q)
                if not row_smi:
                    continue
                fields = _extract_medchem_fields(comp, selected=self.selected_fields)
                tc = morgan_tanimoto_to_query(q, row_smi)
                if not pubchem_hit_passes_tanimoto_threshold(tc, min_t):
                    logs.append(
                        f"{row_smi} | skip (Tanimoto {tc:.4f} < {min_t:.4f})"
                        if tc is not None
                        else f"{row_smi} | skip (no Tanimoto score)"
                    )
                    continue
                fields[COLUMN_TANIMOTO_SIMILARITY] = f"{tc:.4f}"
                cid = getattr(comp, "cid", None)
                results.append(
                    PubChemResult(
                        cid=int(cid) if cid is not None else None, smiles=row_smi, fields=fields
                    )
                )
                logs.append(f"{row_smi} | OK | CID={cid} | Tanimoto={tc:.4f}")
            results.sort(key=_pubchem_similarity_sort_key, reverse=True)
            self.signals.finished.emit(results, logs)
            return

        total = len(self.smiles_list)
        done = 0
        for smi in self.smiles_list:
            if self._cancel:
                logs.append("Cancelled by user.")
                break
            done += 1
            self.signals.progress.emit(done, total, smi)
            try:
                comp = _get_pubchem_compound_by_smiles(smi)
            except Exception as e:
                logs.append(f"{smi} | ERROR: {e}")
                continue
            if comp is None:
                logs.append(f"{smi} | No PubChem result")
                continue
            fields = _extract_medchem_fields(comp, selected=self.selected_fields)
            cid = getattr(comp, "cid", None)
            row_smi = _compound_table_smiles(comp, smi)
            results.append(
                PubChemResult(
                    cid=int(cid) if cid is not None else None, smiles=row_smi, fields=fields
                )
            )
            logs.append(f"{row_smi} | OK | CID={cid}")
        self.signals.finished.emit(results, logs)


_PUBCHEM_FIELD_DEFS: list[tuple[str, str, str, str]] = [
    # (field_key, label, pubchempy attribute, group)
    ("CID", "CID", "cid", "Identifiers / names"),
    ("IUPAC", "IUPAC name", "iupac_name", "Identifiers / names"),
    (FIELD_COMMON_NAME, "Common Name", "", "Identifiers / names"),
    (FIELD_SYNONYMS, "Synonyms", "synonyms", "Identifiers / names"),
    ("InChIKey", "InChIKey", "inchikey", "Identifiers / names"),
    # PubChemPy: canonical_smiles / isomeric_smiles deprecated → connectivity_smiles / smiles
    ("CanonicalSMILES", "Connectivity SMILES (canonical)", "connectivity_smiles", "Structures"),
    ("IsomericSMILES", "Isomeric SMILES", "smiles", "Structures"),
    ("MolecularFormula", "Molecular formula", "molecular_formula", "Structures"),
    ("MolecularWeight", "Molecular weight", "molecular_weight", "PhysChem"),
    ("XlogP", "XlogP", "xlogp", "PhysChem"),
    ("TPSA", "tPSA", "tpsa", "PhysChem"),
    ("Charge", "Formal charge", "charge", "PhysChem"),
    ("HBD", "H-bond donors (HBD)", "hbond_donor_count", "Counts / topology"),
    ("HBA", "H-bond acceptors (HBA)", "hbond_acceptor_count", "Counts / topology"),
    ("RotBonds", "Rotatable bonds", "rotatable_bond_count", "Counts / topology"),
    ("HeavyAtomCount", "Heavy atom count", "heavy_atom_count", "Counts / topology"),
    ("RingCount", "Ring count", "ring_count", "Counts / topology"),
    ("Complexity", "Complexity", "complexity", "Counts / topology"),
]


def _compound_title(comp) -> str:
    """PubChem preferred name (Title) for a PubChemPy ``Compound``."""
    cid = getattr(comp, "cid", None)
    if cid is None:
        return ""
    try:
        import pubchempy as pcp

        rows = pcp.get_properties(["Title"], int(cid), "cid") or []
    except Exception:
        return ""
    if not rows or not isinstance(rows[0], dict):
        return ""
    return str(rows[0].get("Title") or "").strip()


def _compound_synonyms(comp) -> list[str]:
    """Ranked PubChem synonyms; extra PUG request, cached on the Compound."""
    try:
        raw = getattr(comp, "synonyms", None)
    except Exception:
        return []
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    return [str(raw)]


def _names_from_compound(comp, *, want_common: bool, want_synonyms: bool):
    title = _compound_title(comp) if want_common else ""
    syns: list[str] = []
    if want_synonyms or (want_common and not title):
        syns = _compound_synonyms(comp)
    return names_from_title_and_synonyms(title, syns)


def _extract_medchem_fields(comp, *, selected: list[str] | None = None) -> dict[str, str]:
    # PubChemPy Compound objects expose many attributes; extract only what the user requested.
    def g(name: str) -> str:
        v = getattr(comp, name, None)
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v[:20])
        return str(v)

    out: dict[str, str] = {}
    selected_set = set(selected) if selected else {k for (k, _, _, _) in _PUBCHEM_FIELD_DEFS}
    want_common = FIELD_COMMON_NAME in selected_set
    want_synonyms = FIELD_SYNONYMS in selected_set
    for key, _label, attr, _group in _PUBCHEM_FIELD_DEFS:
        if key not in selected_set or key in {FIELD_COMMON_NAME, FIELD_SYNONYMS}:
            continue
        out[key] = g(attr)
    if want_common or want_synonyms:
        names = _names_from_compound(comp, want_common=want_common, want_synonyms=want_synonyms)
        if want_common:
            out[FIELD_COMMON_NAME] = names.common_name
        if want_synonyms:
            out[FIELD_SYNONYMS] = names.synonyms
    return {k: v for k, v in out.items() if v != ""}


class PubChemDialog(QDialog):
    def __init__(
        self, parent=None, *, initial_smiles: list[str] | None = None, auto_query: bool = False
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Query Database — PubChem query")
        self.resize(820, 560)
        self._last: list[PubChemResult] = []
        self._worker: _PubChemBatchWorker | None = None

        root = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        self.rb_pub_identity = QRadioButton("Identity (SMILES lookup)")
        self.rb_pub_similarity = QRadioButton("Similarity (2D Tanimoto, PubChem)")
        self.rb_pub_identity.setChecked(True)
        self._pub_mode_group = QButtonGroup(self)
        self._pub_mode_group.addButton(self.rb_pub_identity)
        self._pub_mode_group.addButton(self.rb_pub_similarity)
        mode_row.addWidget(self.rb_pub_identity)
        mode_row.addWidget(self.rb_pub_similarity)
        mode_row.addStretch()
        root.addLayout(mode_row)

        self.gb_sim = QGroupBox("Similarity parameters (PubChem)")
        sim_form = QFormLayout(self.gb_sim)
        self.spin_tc = QDoubleSpinBox()
        self.spin_tc.setRange(0.30, 1.00)
        self.spin_tc.setDecimals(2)
        self.spin_tc.setSingleStep(0.05)
        self.spin_tc.setValue(0.70)
        self.spin_tc.setToolTip(
            "Minimum Tanimoto similarity for PubChem PUG-REST 2D fingerprint search "
            "(Threshold 1–100 on the PubChem scale; see PubChem documentation)."
        )
        sim_form.addRow("Min. Tanimoto:", self.spin_tc)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 500)
        self.spin_max.setValue(25)
        self.spin_max.setToolTip("Maximum number of compounds returned (PubChem MaxRecords).")
        sim_form.addRow("Max. structures:", self.spin_max)
        self.gb_sim.setEnabled(False)
        self.rb_pub_similarity.toggled.connect(self.gb_sim.setEnabled)
        root.addWidget(self.gb_sim)

        row = QHBoxLayout()
        row.addWidget(QLabel("SMILES:"))
        self.smiles = QLineEdit()
        self.smiles.setPlaceholderText("Paste SMILES here, or use the Sketcher button…")
        row.addWidget(self.smiles, 1)
        self.btn_query = QPushButton("Query")
        self.btn_query.setToolTip(
            "Run PubChem lookup for the SMILES above, or for selected rows if “Only Query Selected” is checked."
        )
        self.btn_query.clicked.connect(self._run_query)
        row.addWidget(self.btn_query)
        self.chk_only_selected = QCheckBox("Only Query Selected")
        self.chk_only_selected.setToolTip(
            "When checked, Query uses SMILES from selected rows in the main table (ignores the text box)."
        )
        row.addWidget(self.chk_only_selected)
        self.btn_sketch = QPushButton("Sketcher…")
        self.btn_sketch.clicked.connect(self._use_sketcher)
        row.addWidget(self.btn_sketch)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)

        gb_fields = QGroupBox("Retrieve fields")
        fields_v = QVBoxLayout(gb_fields)
        btn_all_fields = QHBoxLayout()
        self.btn_pubchem_all_fields = QPushButton("Retrieve all fields")
        self.btn_pubchem_all_fields.setToolTip(
            "Select every field below (larger PubChemPy requests). By default, boxes start unchecked—"
            "pick what you need or use this shortcut."
        )
        self.btn_pubchem_all_fields.clicked.connect(self._pubchem_select_all_fields)
        btn_all_fields.addWidget(self.btn_pubchem_all_fields)
        btn_all_fields.addStretch()
        fields_v.addLayout(btn_all_fields)
        self.field_checks: dict[str, QCheckBox] = {}
        groups: dict[str, list[tuple[str, str, str, str]]] = {}
        for item in _PUBCHEM_FIELD_DEFS:
            groups.setdefault(item[3], []).append(item)

        for group_name in ["Identifiers / names", "Structures", "PhysChem", "Counts / topology"]:
            items = groups.get(group_name, [])
            if not items:
                continue
            gb = QGroupBox(group_name)
            g = QGridLayout(gb)
            for i, (key, label, _attr, _grp) in enumerate(items):
                cb = QCheckBox(label if label == key else f"{label} ({key})")
                cb.setChecked(False)
                self.field_checks[key] = cb
                g.addWidget(cb, i // 2, i % 2)
            fields_v.addWidget(gb)

        root.addWidget(gb_fields)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        apply_monospace_to_text_edit(self.out)
        root.addWidget(self.out, 1)

        bottom = QHBoxLayout()
        self.btn_add = QPushButton("Add result(s) to table")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_table)
        bottom.addWidget(self.btn_add)
        self.btn_add_unique = QPushButton("Add unique structures only")
        self.btn_add_unique.setEnabled(False)
        self.btn_add_unique.setToolTip(
            "Skip rows whose canonical SMILES already exists in the table, "
            "and skip duplicates within this result set."
        )
        self.btn_add_unique.clicked.connect(self._add_unique_to_table)
        bottom.addWidget(self.btn_add_unique)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_query)
        bottom.addWidget(self.btn_cancel)
        bottom.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_query)
        if initial_smiles:
            self.set_smiles_list(initial_smiles)
            if auto_query:
                self._run_query()
        make_window_minimizable(self)

    def _pubchem_select_all_fields(self) -> None:
        for cb in self.field_checks.values():
            cb.setChecked(True)

    def set_smiles_list(self, smiles_list: list[str]) -> None:
        smiles_list = [s.strip() for s in (smiles_list or []) if s and s.strip()]
        self.smiles.setText("\n".join(smiles_list))

    def _parse_smiles_inputs(self) -> list[str]:
        # Accept multiple SMILES separated by newlines/semicolons/commas.
        # Also accept multiple SMILES concatenated by periods, per app workflow.
        raw = (self.smiles.text() or "").strip()
        if not raw:
            return []
        tmp = raw.replace(";", "\n").replace(",", "\n").replace(".", "\n")
        parts = [p.strip() for p in tmp.splitlines() if p.strip()]
        # De-duplicate while preserving order
        out: list[str] = []
        seen = set()
        for p in parts:
            if p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def _resolve_single_query_smiles(self) -> str | None:
        """One reference SMILES for similarity mode (first selected row or first token in the box)."""
        if self.chk_only_selected.isChecked():
            app = self.parent_app
            if app is None:
                QMessageBox.information(self, "PubChem", "Main application is not available.")
                return None
            try:
                lst = app._selected_smiles_strings()
            except Exception:
                lst = []
            if not lst:
                QMessageBox.information(
                    self, "PubChem", "Select one or more rows that have a SMILES value first."
                )
                return None
            return lst[0].strip()
        raw = (self.smiles.text() or "").strip()
        if not raw:
            QMessageBox.information(self, "PubChem", "Enter a SMILES string first.")
            return None
        return raw.split()[0].strip()

    def _use_sketcher(self) -> None:
        # Reuse the app's existing SketcherDialog (but we need the SMILES from its canvas).
        try:
            from ..sketcher import SketcherDialog
        except Exception as e:
            QMessageBox.warning(self, "PubChem", str(e))
            return

        dlg = SketcherDialog(self.parent_app if self.parent_app is not None else self)
        dlg.setModal(True)
        dlg.setWindowModality(Qt.ApplicationModal)
        if dlg.exec() != QDialog.Accepted:
            # Even on cancel/close, user may have drawn something; try to capture it.
            pass

        try:
            parts = dlg.canvas.fragment_smiles_parts()
        except Exception:
            parts = []
        if not parts:
            QMessageBox.information(
                self, "PubChem", "No valid SMILES could be exported from the sketch."
            )
            return
        # Load fragments into the SMILES field; user runs Query when ready.
        self.chk_only_selected.setChecked(False)
        self.smiles.setText("\n".join(parts))
        self.status.setText("SMILES loaded from sketcher — press Query when ready.")

    def _run_query(self) -> None:
        selected_fields = [k for k, cb in self.field_checks.items() if cb.isChecked()]
        if not selected_fields:
            QMessageBox.information(self, "PubChem", "Select at least one field to retrieve.")
            return

        similarity: tuple[float, int] | None = None
        smiles_list: list[str]

        if self.rb_pub_similarity.isChecked():
            one = self._resolve_single_query_smiles()
            if not one:
                return
            smiles_list = [one]
            similarity = (float(self.spin_tc.value()), int(self.spin_max.value()))
        else:
            if self.chk_only_selected.isChecked():
                app = self.parent_app
                if app is None:
                    QMessageBox.information(self, "PubChem", "Main application is not available.")
                    return
                try:
                    smiles_list = app._selected_smiles_strings()
                except Exception:
                    smiles_list = []
                if not smiles_list:
                    QMessageBox.information(
                        self, "PubChem", "Select one or more rows that have a SMILES value first."
                    )
                    return
            else:
                smiles_list = self._parse_smiles_inputs()
                if not smiles_list:
                    QMessageBox.information(
                        self, "PubChem", "Enter at least one SMILES string first."
                    )
                    return

        self._last = []
        self.btn_add.setEnabled(False)
        self.btn_add_unique.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_query.setEnabled(False)
        self.chk_only_selected.setEnabled(False)
        self.btn_sketch.setEnabled(False)
        self.rb_pub_identity.setEnabled(False)
        self.rb_pub_similarity.setEnabled(False)
        self.gb_sim.setEnabled(False)
        n = len(smiles_list)
        self.status.setText(
            f"Starting PubChem {'similarity' if similarity else 'identity'} query… (N={n})"
        )
        self.out.setPlainText("")

        self._worker = _PubChemBatchWorker(
            smiles_list, selected_fields=selected_fields, similarity=similarity
        )
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        start_runnable_on_app_pool(self.parent_app, self._worker)

    def _cancel_query(self) -> None:
        w = getattr(self, "_worker", None)
        if w is not None:
            try:
                w.cancel()
            except Exception:
                pass
        self.status.setText("Cancelling…")

    def _on_progress(self, done: int, total: int, smi: str) -> None:
        self.status.setText(f"Querying PubChem… {done}/{total}  ({smi})")

    def _on_finished(self, results: list, logs: list) -> None:
        self._last = list(results or [])
        self.btn_add.setEnabled(bool(self._last))
        self.btn_add_unique.setEnabled(bool(self._last))
        self.btn_cancel.setEnabled(False)
        self.btn_query.setEnabled(True)
        self.chk_only_selected.setEnabled(True)
        self.btn_sketch.setEnabled(True)
        self.rb_pub_identity.setEnabled(True)
        self.rb_pub_similarity.setEnabled(True)
        self.gb_sim.setEnabled(self.rb_pub_similarity.isChecked())
        self.status.setText(f"Done. Success: {len(self._last)}  Total: {len(logs)}")
        # Display a compact log by default (big batches stay readable).
        self.out.setPlainText("\n".join(str(x) for x in (logs or [])))
        self._worker = None

    def _add_unique_to_table(self) -> None:
        self._add_to_table(unique_only=True)

    def _add_to_table(self, *, unique_only: bool = False) -> None:
        if self.parent_app is None or not self._last:
            return
        app = self.parent_app
        existing = app.existing_canonical_structure_keys() if unique_only else set()
        seen_batch: set[str] = set()
        batch: list[tuple[str, dict[str, str]]] = []
        skipped = 0
        for r in self._last:
            smi = (r.smiles or "").strip()
            if unique_only:
                key = app.canonical_structure_key_from_smiles(smi)
                if key is None:
                    skipped += 1
                    continue
                if key in existing or key in seen_batch:
                    skipped += 1
                    continue
                seen_batch.add(key)
            batch.append((smi, r.fields))
        added = 0
        if batch:
            try:
                added = app.add_rows_from_external_records_batch(batch)
            except Exception:
                skipped += len(batch)
                added = 0
        if hasattr(app, "status_label"):
            if unique_only:
                app.status_label.setText(
                    f"PubChem: added {added} unique row(s); skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(f"PubChem: added {added} row(s) to the table.")
            else:
                app.status_label.setText(
                    "PubChem: no rows were added (see log in this window for errors)."
                )
