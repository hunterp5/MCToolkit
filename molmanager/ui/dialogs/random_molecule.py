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

"""Random ChEMBL molecules dialog (Tools → Random → Molecule)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...chembl_random import RandomChemblMolecule, fetch_random_chembl_molecules
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..strings import TOOL_RANDOM_MOLECULE
from ..threadpool_access import start_runnable_on_app_pool


@dataclass(frozen=True)
class RandomMoleculeDialogParams:
    count: int
    seed: int | None
    add_unique_only: bool


class _RandomChemblSignals(QObject):
    progress = pyqtSignal(int, int)  # have, want
    finished = pyqtSignal(list, str)  # list[RandomChemblMolecule], log
    failed = pyqtSignal(str)


class _RandomChemblWorker(QRunnable):
    def __init__(self, count: int, seed: int | None, signals: _RandomChemblSignals):
        super().__init__()
        self.count = count
        self.seed = seed
        self.signals = signals
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            hits = fetch_random_chembl_molecules(
                self.count,
                seed=self.seed,
                cancel_check=lambda: self._cancel,
                progress=lambda have, want: self.signals.progress.emit(int(have), int(want)),
            )
        except Exception as e:
            self.signals.failed.emit(str(e) or "ChEMBL request failed.")
            return
        lines = [
            f"Requested: {self.count}",
            f"Retrieved: {len(hits)}",
            f"Seed: {self.seed if self.seed is not None else '(none)'}",
            "",
        ]
        for h in hits[:40]:
            lines.append(f"{h.chembl_id}\t{(h.smiles or '')[:80]}")
        if len(hits) > 40:
            lines.append(f"… ({len(hits) - 40} more)")
        self.signals.finished.emit(hits, "\n".join(lines))


class RandomMoleculeDialog(QDialog):
    """Pull a user-specified number of random ChEMBL small molecules into the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_RANDOM_MOLECULE)
        self.setMinimumWidth(480)
        self.resize(560, 420)
        make_window_minimizable(self)

        self._last: list[RandomChemblMolecule] = []
        self._worker: _RandomChemblWorker | None = None
        self._signals = _RandomChemblSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        tip = QLabel(
            "Fetch random small molecules from ChEMBL and add them to the table "
            "(canonical SMILES + ChEMBL_ID)."
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        form = QFormLayout()
        self.count_sb = QSpinBox()
        self.count_sb.setRange(1, 500)
        self.count_sb.setValue(10)
        self.count_sb.setToolTip("How many random ChEMBL compounds to retrieve.")
        form.addRow("Number of molecules:", self.count_sb)

        self.seed_sb = QSpinBox()
        self.seed_sb.setRange(0, 2_147_483_647)
        self.seed_sb.setValue(0)
        self.seed_sb.setSpecialValueText("None")
        self.seed_sb.setToolTip("Optional RNG seed for reproducible sampling (0 = no seed).")
        form.addRow("Seed (optional):", self.seed_sb)

        self.chk_unique = QCheckBox("Skip structures already in the table")
        self.chk_unique.setChecked(True)
        self.chk_unique.setToolTip(
            "When adding results, skip SMILES that match an existing table structure (canonical key)."
        )
        form.addRow("", self.chk_unique)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_fetch = QPushButton("Fetch from ChEMBL")
        self.btn_fetch.clicked.connect(self._start_fetch)
        btn_row.addWidget(self.btn_fetch)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_fetch)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.status = QLabel("Ready.")
        root.addWidget(self.status)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Fetch log…")
        apply_monospace_to_text_edit(self.log)
        root.addWidget(self.log, 1)

        bottom = QHBoxLayout()
        self.btn_add = QPushButton("Add to table")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_table)
        bottom.addWidget(self.btn_add)
        bottom.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        bottom.addWidget(box)
        root.addLayout(bottom)

    def params(self) -> RandomMoleculeDialogParams:
        seed_val = int(self.seed_sb.value())
        return RandomMoleculeDialogParams(
            count=int(self.count_sb.value()),
            seed=None if seed_val == 0 else seed_val,
            add_unique_only=bool(self.chk_unique.isChecked()),
        )

    def _set_busy(self, busy: bool) -> None:
        self.btn_fetch.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.count_sb.setEnabled(not busy)
        self.seed_sb.setEnabled(not busy)
        if busy:
            self.btn_add.setEnabled(False)

    def _start_fetch(self) -> None:
        if self._worker is not None:
            return
        p = self.params()
        self._last = []
        self.btn_add.setEnabled(False)
        self.log.clear()
        self.status.setText(f"Fetching {p.count} random molecule(s) from ChEMBL…")
        self._set_busy(True)
        worker = _RandomChemblWorker(p.count, p.seed, self._signals)
        self._worker = worker
        start_runnable_on_app_pool(self.parent_app, worker)

    def _cancel_fetch(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Cancelling…")

    def _on_progress(self, have: int, want: int) -> None:
        self.status.setText(f"Fetching from ChEMBL… {have}/{want}")

    def _on_finished(self, hits: list, log: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._last = list(hits or [])
        self.btn_add.setEnabled(bool(self._last))
        self.status.setText(f"Done. Retrieved {len(self._last)} molecule(s).")
        self.log.setPlainText(log or "")

    def _on_failed(self, msg: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._last = []
        self.btn_add.setEnabled(False)
        low = (msg or "").lower()
        if "cancel" in low:
            self.status.setText("Cancelled.")
            self.log.setPlainText(msg or "")
            return
        self.status.setText("Failed.")
        self.log.setPlainText(msg or "Unknown error.")
        QMessageBox.warning(self, TOOL_RANDOM_MOLECULE, msg or "ChEMBL request failed.")

    def _add_to_table(self) -> None:
        if self.parent_app is None or not self._last:
            return
        app = self.parent_app
        unique_only = bool(self.chk_unique.isChecked())
        existing = app.existing_canonical_structure_keys() if unique_only else set()
        seen_batch: set[str] = set()
        batch: list[tuple[str, dict[str, str]]] = []
        skipped = 0
        for h in self._last:
            smi = (h.smiles or "").strip()
            if not smi:
                skipped += 1
                continue
            if unique_only:
                key = app.canonical_structure_key_from_smiles(smi)
                if key is None:
                    skipped += 1
                    continue
                if key in existing or key in seen_batch:
                    skipped += 1
                    continue
                seen_batch.add(key)
            batch.append((smi, dict(h.fields)))
        added = 0
        if batch:
            try:
                added = app.add_rows_from_external_records_batch(batch)
            except Exception as e:
                QMessageBox.warning(self, TOOL_RANDOM_MOLECULE, str(e) or "Failed to add rows.")
                return
        if hasattr(app, "status_label"):
            if unique_only:
                app.status_label.setText(
                    f"{TOOL_RANDOM_MOLECULE}: added {added} unique row(s); "
                    f"skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(
                    f"{TOOL_RANDOM_MOLECULE}: added {added} row(s) to the table."
                )
            else:
                app.status_label.setText(f"{TOOL_RANDOM_MOLECULE}: no rows were added.")
        self.status.setText(
            f"Added {added} row(s) to the table" + (f" ({skipped} skipped)." if skipped else ".")
        )

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().reject()
