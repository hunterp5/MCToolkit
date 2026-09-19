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

"""ChEMBL querying and medchem summary via chembl_webresource_client."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
)

from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..strings import COLUMN_TANIMOTO_SIMILARITY
from ..threadpool_access import start_runnable_on_app_pool


@contextmanager
def _quiet_chembl_console() -> Iterator[None]:
    """Raise common HTTP/client loggers to WARNING while ChEMBL runs (fewer console lines)."""
    names = (
        "urllib3",
        "urllib3.connectionpool",
        "urllib3.util",
        "urllib3.util.retry",
        "requests.packages.urllib3",
        "requests",
        "chembl_webresource_client",
    )
    saved: list[tuple[logging.Logger, int]] = []
    for name in names:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level))
        lg.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for lg, level in saved:
            lg.setLevel(level)


@dataclass(frozen=True)
class ChEMBLResult:
    chembl_id: str
    smiles: str
    fields: dict[str, str]
    activities: list[dict[str, Any]]
    targets: list[dict[str, Any]]


def _client():
    try:
        from chembl_webresource_client.new_client import new_client
    except Exception as e:
        raise RuntimeError(
            "chembl_webresource_client is required. Install requirements.txt."
        ) from e
    return new_client


def _get_chembl_molecule_by_smiles(smiles: str) -> dict[str, Any] | None:
    new_client = _client()
    mol = new_client.molecule
    res = mol.filter(molecule_structures__canonical_smiles=smiles)
    if res:
        return dict(res[0])
    # Fallback: try a small contains for slightly different SMILES representations.
    res = mol.filter(molecule_structures__canonical_smiles__contains=smiles[:16])
    return dict(res[0]) if res else None


def _chembl_table_smiles(rec: dict[str, Any]) -> str:
    """Canonical SMILES from a ChEMBL molecule record, or empty string."""
    structs = rec.get("molecule_structures") or {}
    if isinstance(structs, dict):
        cs = structs.get("canonical_smiles")
        if cs:
            return str(cs).strip()
    return ""


def _extract_field_groups(rec: dict[str, Any], *, groups: dict[str, bool]) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not rec:
        return fields

    if groups.get("identity", True):
        for k, out_k in [
            ("molecule_chembl_id", "ChEMBL_ID"),
            ("pref_name", "PrefName"),
            ("molecule_type", "MoleculeType"),
            ("max_phase", "MaxPhase"),
            ("first_approval", "FirstApproval"),
        ]:
            v = rec.get(k, None)
            if v is not None and str(v) != "":
                fields[out_k] = str(v)

    if groups.get("structures", True):
        structs = rec.get("molecule_structures") or {}
        if isinstance(structs, dict):
            if structs.get("canonical_smiles"):
                fields["CanonicalSMILES"] = str(structs["canonical_smiles"])
            if structs.get("standard_inchi_key"):
                fields["InChIKey"] = str(structs["standard_inchi_key"])

    if groups.get("properties", True):
        props = rec.get("molecule_properties") or {}
        if isinstance(props, dict):
            wanted = groups.get("properties_selected")
            if wanted is None:
                wanted = [
                    "full_mwt",
                    "alogp",
                    "psa",
                    "hba",
                    "hbd",
                    "rtb",
                    "aromatic_rings",
                    "heavy_atoms",
                    "ro5_violations",
                    "qed_weighted",
                ]
            else:
                wanted = list(wanted)
            key_to_out = {
                "full_mwt": "MolecularWeight",
                "alogp": "AlogP",
                "psa": "PSA",
                "hba": "HBA",
                "hbd": "HBD",
                "rtb": "RotBonds",
                "aromatic_rings": "AromaticRings",
                "heavy_atoms": "HeavyAtomCount",
                "ro5_violations": "Ro5Violations",
                "qed_weighted": "QED",
                "full_molformula": "MolecularFormula",
                "mw_freebase": "MW_Freebase",
                "num_ro5_violations": "Ro5Violations",
                "num_lipinski_ro5_violations": "Ro5Violations",
            }
            for k in wanted:
                v = props.get(k, None)
                if v is not None and str(v) != "":
                    fields[key_to_out.get(k, k)] = str(v)

    return fields


def _fetch_activities(
    chembl_id: str,
    *,
    limit: int,
    only_with_pchembl: bool,
) -> list[dict[str, Any]]:
    new_client = _client()
    activity = new_client.activity
    q = activity.filter(molecule_chembl_id=chembl_id)
    if only_with_pchembl:
        q = q.filter(pchembl_value__isnull=False)
    # Keep a compact, high-signal set of fields.
    q = q.only(
        [
            "activity_id",
            "assay_chembl_id",
            "target_chembl_id",
            "standard_type",
            "standard_relation",
            "standard_value",
            "standard_units",
            "pchembl_value",
            "confidence_score",
        ]
    )
    out: list[dict[str, Any]] = []
    for i, rec in enumerate(q):
        if i >= limit:
            break
        if isinstance(rec, dict):
            out.append(rec)
        else:
            out.append(dict(rec))

    # Sort by pchembl_value desc when present (most potent/highest pChEMBL first).
    def key(r: dict[str, Any]) -> float:
        v = r.get("pchembl_value", None)
        try:
            return float(v)
        except Exception:
            return float("-inf")

    out.sort(key=key, reverse=True)
    return out


def _fetch_targets(target_ids: list[str], *, limit: int) -> list[dict[str, Any]]:
    new_client = _client()
    target = new_client.target
    out: list[dict[str, Any]] = []
    seen = set()
    for tid in target_ids:
        if not tid or tid in seen:
            continue
        seen.add(tid)
        try:
            rec = target.get(tid)
        except Exception:
            continue
        if rec is None:
            continue
        d = dict(rec) if not isinstance(rec, dict) else rec
        slim = {
            "target_chembl_id": d.get("target_chembl_id", tid),
            "pref_name": d.get("pref_name", ""),
            "target_type": d.get("target_type", ""),
            "organism": d.get("organism", ""),
        }
        out.append({k: v for k, v in slim.items() if v not in (None, "")})
        if len(out) >= limit:
            break
    return out


class _QuerySignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list, list, str, str)  # results, logs, activities_tsv, targets_tsv


class _ChEMBLBatchWorker(QRunnable):
    def __init__(
        self,
        smiles_list: list[str],
        *,
        field_groups: dict[str, bool],
        property_keys: list[str],
        get_activities: bool,
        get_targets: bool,
        activity_limit: int,
        target_limit: int,
        only_with_pchembl: bool,
        similarity: tuple[float, int] | None = None,
    ):
        super().__init__()
        self.smiles_list = smiles_list
        self.field_groups = field_groups
        self.property_keys = property_keys
        self.get_activities = get_activities
        self.get_targets = get_targets
        self.activity_limit = activity_limit
        self.target_limit = target_limit
        self.only_with_pchembl = only_with_pchembl
        self.similarity = similarity
        self.signals = _QuerySignals()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        with _quiet_chembl_console():
            self._run_impl()

    def _run_impl(self) -> None:
        from chembl_webresource_client.new_client import new_client
        from chembl_webresource_client.settings import Settings

        results: list[ChEMBLResult] = []
        logs: list[str] = []
        acts_rows: list[str] = [
            "SMILES\tChEMBL_ID\tpchembl_value\tstandard_type\tstandard_relation\tstandard_value\tstandard_units\tconfidence_score\tassay_chembl_id\ttarget_chembl_id\tactivity_id"
        ]
        targ_rows: list[str] = ["ChEMBL_ID\ttarget_chembl_id\tpref_name\ttarget_type\torganism"]

        if self.similarity is not None:
            min_t, max_hits = self.similarity
            q = (self.smiles_list[0] if self.smiles_list else "").strip()
            max_hits = max(1, min(500, int(max_hits)))
            api_t = max(70, min(100, int(round(float(min_t) * 100))))
            if api_t != int(round(float(min_t) * 100)):
                logs.append(
                    f"Note: ChEMBL similarity filter accepts thresholds 70–100 only; "
                    f"using {api_t} (Tanimoto ≥ {api_t / 100:.2f})."
                )
            settings = Settings.Instance()
            prev_limit = settings.MAX_LIMIT
            settings.MAX_LIMIT = min(1000, max(100, max_hits + 20))
            try:
                sim = new_client.similarity
                raw_list = list(sim.filter(smiles=q, similarity=str(api_t)))
            except Exception as e:
                settings.MAX_LIMIT = prev_limit
                logs.append(f"{q} | similarity ERROR: {e}")
                self.signals.finished.emit(
                    results, logs, "\n".join(acts_rows), "\n".join(targ_rows)
                )
                return
            finally:
                settings.MAX_LIMIT = prev_limit

            def _chembl_similarity_sort_key(rec) -> float:
                d = dict(rec) if not isinstance(rec, dict) else rec
                try:
                    return float(d.get("similarity") or 0.0)
                except Exception:
                    return -1.0

            raw_list.sort(key=_chembl_similarity_sort_key, reverse=True)
            raw_list = raw_list[:max_hits]
            logs.append(
                f"Similarity (ChEMBL): query={q!r}  min_Tanimoto≥{api_t / 100:.2f}  max_hits={max_hits}  "
                f"retrieved={len(raw_list)}"
            )
            total = len(raw_list)
            done = 0
            for rec in raw_list:
                if self._cancel:
                    logs.append("Cancelled by user.")
                    break
                if not isinstance(rec, dict):
                    rec = dict(rec)
                done += 1
                chembl_id = str(rec.get("molecule_chembl_id", "") or "")
                table_smi = _chembl_table_smiles(rec) or q
                self.signals.progress.emit(done, max(total, 1), table_smi)
                fg = dict(self.field_groups)
                fg["properties_selected"] = list(self.property_keys)
                fields = _extract_field_groups(rec, groups=fg)
                simv = rec.get("similarity")
                if simv is not None:
                    try:
                        fields[COLUMN_TANIMOTO_SIMILARITY] = f"{float(simv) / 100.0:.4f}"
                    except Exception:
                        fields[COLUMN_TANIMOTO_SIMILARITY] = str(simv)

                activities: list[dict[str, Any]] = []
                targets: list[dict[str, Any]] = []
                if self.get_activities and chembl_id:
                    try:
                        activities = _fetch_activities(
                            chembl_id,
                            limit=self.activity_limit,
                            only_with_pchembl=self.only_with_pchembl,
                        )
                    except Exception as e:
                        logs.append(f"{table_smi} | {chembl_id} | Activities ERROR: {e}")
                        activities = []
                if self.get_targets and activities:
                    tids = [str(a.get("target_chembl_id", "") or "") for a in activities]
                    tids = [t for t in tids if t]
                    try:
                        targets = _fetch_targets(tids, limit=self.target_limit)
                    except Exception as e:
                        logs.append(f"{table_smi} | {chembl_id} | Targets ERROR: {e}")
                        targets = []
                if activities:
                    best = activities[0]
                    if best.get("pchembl_value") not in (None, ""):
                        fields["Best_pChEMBL"] = str(best.get("pchembl_value"))
                    if best.get("standard_type") not in (None, ""):
                        fields["Best_StandardType"] = str(best.get("standard_type"))
                    if best.get("target_chembl_id") not in (None, ""):
                        fields["Best_TargetChEMBL_ID"] = str(best.get("target_chembl_id"))

                results.append(
                    ChEMBLResult(
                        chembl_id=chembl_id,
                        smiles=table_smi,
                        fields=fields,
                        activities=activities,
                        targets=targets,
                    )
                )
                logs.append(f"{table_smi} | OK | ChEMBL_ID={chembl_id}")

                for a in activities:
                    acts_rows.append(
                        "\t".join(
                            [
                                table_smi,
                                chembl_id,
                                str(a.get("pchembl_value", "") or ""),
                                str(a.get("standard_type", "") or ""),
                                str(a.get("standard_relation", "") or ""),
                                str(a.get("standard_value", "") or ""),
                                str(a.get("standard_units", "") or ""),
                                str(a.get("confidence_score", "") or ""),
                                str(a.get("assay_chembl_id", "") or ""),
                                str(a.get("target_chembl_id", "") or ""),
                                str(a.get("activity_id", "") or ""),
                            ]
                        )
                    )
                for t in targets:
                    targ_rows.append(
                        "\t".join(
                            [
                                chembl_id,
                                str(t.get("target_chembl_id", "") or ""),
                                str(t.get("pref_name", "") or ""),
                                str(t.get("target_type", "") or ""),
                                str(t.get("organism", "") or ""),
                            ]
                        )
                    )

            self.signals.finished.emit(results, logs, "\n".join(acts_rows), "\n".join(targ_rows))
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
                rec = _get_chembl_molecule_by_smiles(smi)
            except Exception as e:
                logs.append(f"{smi} | ERROR: {e}")
                continue
            if not rec:
                logs.append(f"{smi} | No ChEMBL result")
                continue
            chembl_id = str(rec.get("molecule_chembl_id", "") or "")
            table_smi = _chembl_table_smiles(rec) or smi.strip()
            fg = dict(self.field_groups)
            fg["properties_selected"] = list(self.property_keys)
            fields = _extract_field_groups(rec, groups=fg)

            activities: list[dict[str, Any]] = []
            targets: list[dict[str, Any]] = []
            if self.get_activities and chembl_id:
                try:
                    activities = _fetch_activities(
                        chembl_id,
                        limit=self.activity_limit,
                        only_with_pchembl=self.only_with_pchembl,
                    )
                except Exception as e:
                    logs.append(f"{smi} | {chembl_id} | Activities ERROR: {e}")
                    activities = []

            if self.get_targets and activities:
                tids = [str(a.get("target_chembl_id", "") or "") for a in activities]
                tids = [t for t in tids if t]
                try:
                    targets = _fetch_targets(tids, limit=self.target_limit)
                except Exception as e:
                    logs.append(f"{smi} | {chembl_id} | Targets ERROR: {e}")
                    targets = []

            # Add small summary fields from activities so "Add to table" can carry them.
            if activities:
                best = activities[0]
                if best.get("pchembl_value") not in (None, ""):
                    fields["Best_pChEMBL"] = str(best.get("pchembl_value"))
                if best.get("standard_type") not in (None, ""):
                    fields["Best_StandardType"] = str(best.get("standard_type"))
                if best.get("target_chembl_id") not in (None, ""):
                    fields["Best_TargetChEMBL_ID"] = str(best.get("target_chembl_id"))

            results.append(
                ChEMBLResult(
                    chembl_id=chembl_id,
                    smiles=table_smi,
                    fields=fields,
                    activities=activities,
                    targets=targets,
                )
            )
            logs.append(f"{table_smi} | OK | ChEMBL_ID={chembl_id}")

            for a in activities:
                acts_rows.append(
                    "\t".join(
                        [
                            table_smi,
                            chembl_id,
                            str(a.get("pchembl_value", "") or ""),
                            str(a.get("standard_type", "") or ""),
                            str(a.get("standard_relation", "") or ""),
                            str(a.get("standard_value", "") or ""),
                            str(a.get("standard_units", "") or ""),
                            str(a.get("confidence_score", "") or ""),
                            str(a.get("assay_chembl_id", "") or ""),
                            str(a.get("target_chembl_id", "") or ""),
                            str(a.get("activity_id", "") or ""),
                        ]
                    )
                )

            for t in targets:
                targ_rows.append(
                    "\t".join(
                        [
                            chembl_id,
                            str(t.get("target_chembl_id", "") or ""),
                            str(t.get("pref_name", "") or ""),
                            str(t.get("target_type", "") or ""),
                            str(t.get("organism", "") or ""),
                        ]
                    )
                )

        self.signals.finished.emit(results, logs, "\n".join(acts_rows), "\n".join(targ_rows))


class ChEMBLDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Query Database — ChEMBL query")
        self.resize(980, 640)

        self._last: list[ChEMBLResult] = []
        self._worker: _ChEMBLBatchWorker | None = None
        self._activities_tsv = ""
        self._targets_tsv = ""

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("SMILES:"))
        self.smiles = QLineEdit()
        self.smiles.setPlaceholderText("Paste SMILES here, or use the Sketcher button…")
        top.addWidget(self.smiles, 1)
        self.btn_query = QPushButton("Query")
        self.btn_query.setToolTip(
            "Run ChEMBL lookup for the SMILES above, or for selected rows if “Only Query Selected” is checked."
        )
        self.btn_query.clicked.connect(self._run_query)
        top.addWidget(self.btn_query)
        self.chk_only_selected = QCheckBox("Only Query Selected")
        self.chk_only_selected.setToolTip(
            "When checked, Query uses SMILES from selected rows in the main table (ignores the text box)."
        )
        top.addWidget(self.chk_only_selected)
        self.btn_sketch = QPushButton("Sketcher…")
        self.btn_sketch.clicked.connect(self._use_sketcher)
        top.addWidget(self.btn_sketch)
        root.addLayout(top)

        mode_row = QHBoxLayout()
        self.rb_chembl_identity = QRadioButton("Identity (SMILES lookup)")
        self.rb_chembl_similarity = QRadioButton("Similarity (2D Tanimoto, ChEMBL)")
        self.rb_chembl_identity.setChecked(True)
        self._chembl_mode_group = QButtonGroup(self)
        self._chembl_mode_group.addButton(self.rb_chembl_identity)
        self._chembl_mode_group.addButton(self.rb_chembl_similarity)
        mode_row.addWidget(self.rb_chembl_identity)
        mode_row.addWidget(self.rb_chembl_similarity)
        mode_row.addStretch()
        root.addLayout(mode_row)

        self.gb_sim = QGroupBox("Similarity parameters (ChEMBL)")
        sim_form = QFormLayout(self.gb_sim)
        self.spin_tc = QDoubleSpinBox()
        self.spin_tc.setRange(0.30, 1.00)
        self.spin_tc.setDecimals(2)
        self.spin_tc.setSingleStep(0.05)
        self.spin_tc.setValue(0.70)
        self.spin_tc.setToolTip(
            "Minimum Tanimoto similarity for ChEMBL cartridge search. "
            "The public API only accepts thresholds from 0.70 to 1.00 (70–100); lower values are raised to 0.70."
        )
        sim_form.addRow("Min. Tanimoto:", self.spin_tc)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 500)
        self.spin_max.setValue(25)
        self.spin_max.setToolTip("Maximum number of similar molecules to process.")
        sim_form.addRow("Max. structures:", self.spin_max)
        self.gb_sim.setEnabled(False)
        self.rb_chembl_similarity.toggled.connect(self.gb_sim.setEnabled)
        root.addWidget(self.gb_sim)

        opts = QHBoxLayout()
        gb_fields = QGroupBox("Retrieve fields")
        f_lyt = QVBoxLayout(gb_fields)
        btn_all_row = QHBoxLayout()
        self.btn_chembl_all_fields = QPushButton("Retrieve all fields")
        self.btn_chembl_all_fields.setToolTip(
            "Enable identity, structures, every molecule property, activities, targets, "
            "and the pChEMBL-only filter (heavier API usage)."
        )
        self.btn_chembl_all_fields.clicked.connect(self._chembl_select_all_fields)
        btn_all_row.addWidget(self.btn_chembl_all_fields)
        btn_all_row.addStretch()
        f_lyt.addLayout(btn_all_row)
        top_fields = QHBoxLayout()
        self.chk_identity = QCheckBox("Identity")
        self.chk_identity.setChecked(True)
        self.chk_structures = QCheckBox("Structures")
        self.chk_structures.setChecked(True)
        top_fields.addWidget(self.chk_identity)
        top_fields.addWidget(self.chk_structures)
        top_fields.addStretch()
        f_lyt.addLayout(top_fields)

        # Individual ChEMBL molecule_properties checkboxes.
        self._prop_defs: list[tuple[str, str]] = [
            ("full_mwt", "Molecular Weight (full_mwt)"),
            ("mw_freebase", "MW Freebase (mw_freebase)"),
            ("alogp", "AlogP (alogp)"),
            ("psa", "PSA (psa)"),
            ("hbd", "HBD (hbd)"),
            ("hba", "HBA (hba)"),
            ("rtb", "Rotatable Bonds (rtb)"),
            ("aromatic_rings", "Aromatic Rings (aromatic_rings)"),
            ("heavy_atoms", "Heavy Atoms (heavy_atoms)"),
            ("ro5_violations", "Ro5 Violations (ro5_violations)"),
            ("qed_weighted", "QED (qed_weighted)"),
        ]
        gb_props = QGroupBox("Molecule properties")
        props_v = QVBoxLayout(gb_props)
        self.prop_checks: dict[str, QCheckBox] = {}

        def add_prop_group(title: str, keys: list[str]) -> None:
            gb = QGroupBox(title)
            g = QGridLayout(gb)
            items = [(k, dict(self._prop_defs).get(k, k)) for k in keys]
            for i, (k, label) in enumerate(items):
                cb = QCheckBox(label)
                cb.setChecked(False)
                self.prop_checks[k] = cb
                g.addWidget(cb, i // 2, i % 2)
            props_v.addWidget(gb)

        # Categorized like PubChem for easier scanning.
        add_prop_group("PhysChem", ["full_mwt", "mw_freebase", "alogp", "psa"])
        add_prop_group("H-bonding", ["hbd", "hba"])
        add_prop_group("Topology / rings", ["rtb", "heavy_atoms", "aromatic_rings"])
        add_prop_group("Rules / scores", ["ro5_violations", "qed_weighted"])

        f_lyt.addWidget(gb_props)
        opts.addWidget(gb_fields, 2)

        gb_assoc = QGroupBox("Associations")
        aform = QFormLayout(gb_assoc)
        self.chk_activities = QCheckBox("Activities (bioactivity)")
        self.chk_activities.setChecked(False)
        self.spin_act = QSpinBox()
        self.spin_act.setRange(0, 2000)
        self.spin_act.setValue(50)
        self.chk_targets = QCheckBox("Targets (from activities)")
        self.chk_targets.setChecked(False)
        self.spin_targ = QSpinBox()
        self.spin_targ.setRange(0, 500)
        self.spin_targ.setValue(25)
        self.chk_only_pchembl = QCheckBox("Only activities with pChEMBL value")
        self.chk_only_pchembl.setChecked(False)
        aform.addRow(self.chk_activities)
        aform.addRow("Max activities / molecule:", self.spin_act)
        aform.addRow(self.chk_targets)
        aform.addRow("Max targets / molecule:", self.spin_targ)
        aform.addRow(self.chk_only_pchembl)
        opts.addWidget(gb_assoc, 3)
        root.addLayout(opts)

        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)

        self.tabs = QTabWidget()
        self.tab_log = QTextEdit()
        self.tab_log.setReadOnly(True)
        apply_monospace_to_text_edit(self.tab_log)
        self.tabs.addTab(self.tab_log, "Log")

        self.tab_summary = QTextEdit()
        self.tab_summary.setReadOnly(True)
        apply_monospace_to_text_edit(self.tab_summary)
        self.tabs.addTab(self.tab_summary, "Summary")

        self.tab_acts = QTextEdit()
        self.tab_acts.setReadOnly(True)
        apply_monospace_to_text_edit(self.tab_acts)
        self.tabs.addTab(self.tab_acts, "Activities (TSV)")

        self.tab_targets = QTextEdit()
        self.tab_targets.setReadOnly(True)
        apply_monospace_to_text_edit(self.tab_targets)
        self.tabs.addTab(self.tab_targets, "Targets (TSV)")

        root.addWidget(self.tabs, 1)

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
        make_window_minimizable(self)

    def _chembl_select_all_fields(self) -> None:
        self.chk_identity.setChecked(True)
        self.chk_structures.setChecked(True)
        for cb in self.prop_checks.values():
            cb.setChecked(True)
        self.chk_activities.setChecked(True)
        self.chk_targets.setChecked(True)
        self.chk_only_pchembl.setChecked(True)

    def _resolve_single_query_smiles(self) -> str | None:
        if self.chk_only_selected.isChecked():
            app = self.parent_app
            if app is None:
                QMessageBox.information(self, "ChEMBL", "Main application is not available.")
                return None
            try:
                lst = app._selected_smiles_strings()
            except Exception:
                lst = []
            if not lst:
                QMessageBox.information(
                    self, "ChEMBL", "Select one or more rows that have a SMILES value first."
                )
                return None
            return lst[0].strip()
        raw = (self.smiles.text() or "").strip()
        if not raw:
            QMessageBox.information(self, "ChEMBL", "Enter a SMILES string first.")
            return None
        return raw.split()[0].strip()

    def _parse_smiles_inputs(self) -> list[str]:
        raw = (self.smiles.text() or "").strip()
        if not raw:
            return []
        tmp = raw.replace(";", "\n").replace(",", "\n").replace(".", "\n")
        parts = [p.strip() for p in tmp.splitlines() if p.strip()]
        out: list[str] = []
        seen = set()
        for p in parts:
            if p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def set_smiles_list(self, smiles_list: list[str]) -> None:
        smiles_list = [s.strip() for s in (smiles_list or []) if s and s.strip()]
        self.smiles.setText("\n".join(smiles_list))

    def _use_sketcher(self) -> None:
        try:
            from ..sketcher import SketcherDialog
        except Exception as e:
            QMessageBox.warning(self, "ChEMBL", str(e))
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
                self, "ChEMBL", "No valid SMILES could be exported from the sketch."
            )
            return
        self.chk_only_selected.setChecked(False)
        self.set_smiles_list(parts)
        self.status.setText("SMILES loaded from sketcher — press Query when ready.")

    def _run_query(self) -> None:
        property_keys = [k for k, cb in self.prop_checks.items() if cb.isChecked()]
        field_groups = {
            "identity": self.chk_identity.isChecked(),
            "structures": self.chk_structures.isChecked(),
            "properties": bool(property_keys),
        }
        get_acts = self.chk_activities.isChecked() and self.spin_act.value() > 0
        get_targs = self.chk_targets.isChecked() and self.spin_targ.value() > 0

        similarity: tuple[float, int] | None = None
        smiles_list: list[str]

        if self.rb_chembl_similarity.isChecked():
            one = self._resolve_single_query_smiles()
            if not one:
                return
            smiles_list = [one]
            similarity = (float(self.spin_tc.value()), int(self.spin_max.value()))
        else:
            if self.chk_only_selected.isChecked():
                app = self.parent_app
                if app is None:
                    QMessageBox.information(self, "ChEMBL", "Main application is not available.")
                    return
                try:
                    smiles_list = app._selected_smiles_strings()
                except Exception:
                    smiles_list = []
                if not smiles_list:
                    QMessageBox.information(
                        self, "ChEMBL", "Select one or more rows that have a SMILES value first."
                    )
                    return
            else:
                smiles_list = self._parse_smiles_inputs()
                if not smiles_list:
                    QMessageBox.information(
                        self, "ChEMBL", "Enter at least one SMILES string first."
                    )
                    return

        self._last = []
        self._activities_tsv = ""
        self._targets_tsv = ""
        self.btn_add.setEnabled(False)
        self.btn_add_unique.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_query.setEnabled(False)
        self.chk_only_selected.setEnabled(False)
        self.btn_sketch.setEnabled(False)
        self.rb_chembl_identity.setEnabled(False)
        self.rb_chembl_similarity.setEnabled(False)
        self.gb_sim.setEnabled(False)
        self.status.setText(
            f"Starting ChEMBL {'similarity' if similarity else 'identity'} query… (N={len(smiles_list)})"
        )
        self.tab_log.setPlainText("")
        self.tab_summary.setPlainText("")
        self.tab_acts.setPlainText("")
        self.tab_targets.setPlainText("")

        self._worker = _ChEMBLBatchWorker(
            smiles_list,
            field_groups=field_groups,
            property_keys=property_keys,
            get_activities=get_acts,
            get_targets=get_targs,
            activity_limit=int(self.spin_act.value()),
            target_limit=int(self.spin_targ.value()),
            only_with_pchembl=bool(self.chk_only_pchembl.isChecked()),
            similarity=similarity,
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
        self.status.setText(f"Querying ChEMBL… {done}/{total}  ({smi})")

    def _on_finished(self, results: list, logs: list, acts_tsv: str, targets_tsv: str) -> None:
        self._last = list(results or [])
        self._activities_tsv = acts_tsv or ""
        self._targets_tsv = targets_tsv or ""

        self.btn_add.setEnabled(bool(self._last))
        self.btn_add_unique.setEnabled(bool(self._last))
        self.btn_cancel.setEnabled(False)
        self.btn_query.setEnabled(True)
        self.chk_only_selected.setEnabled(True)
        self.btn_sketch.setEnabled(True)
        self.rb_chembl_identity.setEnabled(True)
        self.rb_chembl_similarity.setEnabled(True)
        self.gb_sim.setEnabled(self.rb_chembl_similarity.isChecked())
        self.status.setText(f"Done. Success: {len(self._last)}  Total: {len(logs)}")
        self.tab_log.setPlainText("\n".join(str(x) for x in (logs or [])))
        self.tab_acts.setPlainText(self._activities_tsv)
        self.tab_targets.setPlainText(self._targets_tsv)

        # Summary: concise per-molecule overview.
        lines: list[str] = []
        for r in self._last:
            lines.append(
                f"{r.smiles} | {r.chembl_id} | activities={len(r.activities)} | targets={len(r.targets)}"
            )
        self.tab_summary.setPlainText("\n".join(lines))
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
                    f"ChEMBL: added {added} unique row(s); skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(f"ChEMBL: added {added} row(s) to the table.")
            else:
                app.status_label.setText(
                    "ChEMBL: no rows were added (see log in this window for errors)."
                )
