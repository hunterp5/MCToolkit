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

"""Live physical-properties panel for the chemical sketcher."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QRunnable, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)
from mctoolkit.chem.sketch_physical_properties import (
    SketchPhysicalProperties,
    compute_ionization_properties as _compute_ionization_properties,
    compute_rdkit_physical_properties,
    compute_sketch_physical_properties as _compute_sketch_physical_properties,
    copy_mol,
)
from mctoolkit.ui.qt_widget_utils import make_window_minimizable
from mctoolkit.ui.threadpool_access import start_runnable_on_app_pool
from mctoolkit.workers.ionization_parallel import predict_microstates_for_sketch

if TYPE_CHECKING:
    from .dialog import SketcherDialog

logger = logging.getLogger(__name__)

_IONIZATION_ERROR_TEXT = "Error"
_PKA_CALC_FAILED = "pKa calculation failed"


def compute_ionization_properties(
    mol: Any,
    *,
    cancel_event: threading.Event | None = None,
    states: list | None = None,
) -> dict[str, Any]:
    """Return LogD / pKa / AB-MPS / CNS MPO from a Uni-pKa ionization ensemble."""
    return _compute_ionization_properties(
        mol,
        cancel_event=cancel_event,
        states=states,
        predict_states=predict_microstates_for_sketch,
    )


def compute_sketch_physical_properties(
    mol: Any,
    *,
    with_ionization: bool = True,
) -> SketchPhysicalProperties:
    """Full property bundle for tests and one-shot callers."""
    return _compute_sketch_physical_properties(
        mol,
        with_ionization=with_ionization,
        predict_states=predict_microstates_for_sketch,
    )


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _fmt_pka(values: tuple[float, ...] | None, *, approx: bool, pending: bool) -> str:
    if pending:
        return "…"
    if not values:
        return "—"
    text = ", ".join(f"{v:.2f}" for v in values)
    if approx:
        return f"{text} (approx)"
    return text


class _IonizationSignals(QObject):
    finished = Signal(int, object)  # generation, result dict
    failed = Signal(int, str)


class _IonizationWorker(QRunnable):
    def __init__(
        self,
        mol: Any,
        generation: int,
        signals: _IonizationSignals,
        cancel_event: threading.Event,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._mol = mol
        self._generation = generation
        self._signals = signals
        self._cancel_event = cancel_event

    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                self._signals.failed.emit(self._generation, "cancelled")
                return
            result = compute_ionization_properties(self._mol, cancel_event=self._cancel_event)
        except Exception as exc:
            msg = str(exc) or _PKA_CALC_FAILED
            if msg != "cancelled":
                logger.debug("sketcher ionization failed: %s", msg)
            self._signals.failed.emit(self._generation, msg)
            return
        if self._cancel_event.is_set():
            self._signals.failed.emit(self._generation, "cancelled")
            return
        self._signals.finished.emit(self._generation, result)


class SketchPhysicalPropertiesDialog(QDialog):
    """Modeless panel; values refresh when the sketch changes."""

    def __init__(self, sketcher: SketcherDialog):
        super().__init__(sketcher)
        self._sketcher = sketcher
        self.setWindowTitle("Physical Properties")
        self.setModal(False)
        make_window_minimizable(self)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(320)

        self._generation = 0
        self._active_generation = 0
        self._ion_busy = False
        self._pending_mol: Any = None
        self._pending_generation = 0
        self._cancel_event = threading.Event()
        self._ion_signals = _IonizationSignals(self)
        self._ion_signals.finished.connect(self._on_ionization_finished)
        self._ion_signals.failed.connect(self._on_ionization_failed)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)

        self._val_mw = QLabel("—")
        self._val_tpsa = QLabel("—")
        self._val_logp = QLabel("—")
        self._val_logd = QLabel("—")
        self._val_pka = QLabel("—")
        self._val_ab_mps = QLabel("—")
        self._val_cns_mpo = QLabel("—")
        self._val_qed = QLabel("—")
        self._val_ro5_pass = QLabel("—")
        self._val_ro5_viol = QLabel("—")
        value_labels = (
            self._val_mw,
            self._val_tpsa,
            self._val_logp,
            self._val_logd,
            self._val_pka,
            self._val_ab_mps,
            self._val_cns_mpo,
            self._val_qed,
            self._val_ro5_pass,
            self._val_ro5_viol,
        )
        for lab in value_labels:
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form.addRow("MW", self._val_mw)
        form.addRow("TPSA", self._val_tpsa)
        form.addRow("LogP", self._val_logp)
        form.addRow("LogD (7.4)", self._val_logd)
        form.addRow("pKa", self._val_pka)
        form.addRow("AB-MPS", self._val_ab_mps)
        form.addRow("CNS MPO", self._val_cns_mpo)
        form.addRow("QED Score", self._val_qed)
        form.addRow("RO5 Pass", self._val_ro5_pass)
        form.addRow("RO5 Violations", self._val_ro5_viol)
        root.addLayout(form)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh_now)

    def schedule_refresh(self) -> None:
        """Debounce sketch edits before recomputing."""
        self._timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._timer.stop()
        self._cancel_event.set()
        self._pending_mol = None
        super().closeEvent(event)

    def _clear_all(self) -> None:
        self._val_mw.setText("—")
        self._val_tpsa.setText("—")
        self._val_logp.setText("—")
        self._clear_ionization_tooltips()
        self._val_logd.setText("—")
        self._val_pka.setText("—")
        self._val_ab_mps.setText("—")
        self._val_cns_mpo.setText("—")
        self._val_qed.setText("—")
        self._val_ro5_pass.setText("—")
        self._val_ro5_viol.setText("—")

    def _clear_ionization_tooltips(self) -> None:
        for lab in (self._val_logd, self._val_pka, self._val_ab_mps, self._val_cns_mpo):
            lab.setToolTip("")

    def _set_ionization_pending(self) -> None:
        self._clear_ionization_tooltips()
        self._val_logd.setText("…")
        self._val_pka.setText("…")
        self._val_ab_mps.setText("…")
        self._val_cns_mpo.setText("…")

    def _set_ionization_error(self, msg: str) -> None:
        tip = msg if msg and msg != "cancelled" else _PKA_CALC_FAILED
        for lab in (self._val_logd, self._val_pka, self._val_ab_mps, self._val_cns_mpo):
            lab.setText(_IONIZATION_ERROR_TEXT)
            lab.setToolTip(tip)

    def _refresh_now(self) -> None:
        self._generation += 1
        gen = self._generation
        # Cancel any in-flight process-pool job; coalesced pending work uses the new gen.
        self._cancel_event.set()
        mol = None
        try:
            mol = self._sketcher._sketch_mol_for_3d()
        except Exception:
            mol = None

        fast = compute_rdkit_physical_properties(mol)
        if fast.error or mol is None:
            self._pending_mol = None
            self._clear_all()
            return

        self._val_mw.setText(_fmt_num(fast.mw, 2))
        self._val_tpsa.setText(_fmt_num(fast.tpsa, 2))
        self._val_logp.setText(_fmt_num(fast.logp, 2))
        self._val_qed.setText(_fmt_num(fast.qed, 3))
        self._val_ro5_pass.setText(fast.ro5_pass or "—")
        self._val_ro5_viol.setText(
            "—" if fast.ro5_violations is None else str(int(fast.ro5_violations))
        )
        self._set_ionization_pending()

        try:
            mol_copy = copy_mol(mol)
        except Exception:
            self._set_ionization_error("invalid molecule")
            return

        self._start_or_coalesce_ionization(mol_copy, gen)

    def _start_or_coalesce_ionization(self, mol: Any, generation: int) -> None:
        if self._ion_busy:
            self._pending_mol = mol
            self._pending_generation = generation
            return
        self._ion_busy = True
        self._active_generation = generation
        self._cancel_event = threading.Event()
        worker = _IonizationWorker(mol, generation, self._ion_signals, self._cancel_event)
        start_runnable_on_app_pool(getattr(self._sketcher, "parent_app", None), worker)

    def _drain_pending_ionization(self) -> None:
        pending = self._pending_mol
        gen = self._pending_generation
        self._pending_mol = None
        if pending is None:
            return
        if gen != self._generation:
            return
        self._start_or_coalesce_ionization(pending, gen)

    def _release_ionization_busy(self, generation: int) -> None:
        if generation == self._active_generation:
            self._ion_busy = False

    def _on_ionization_finished(self, generation: int, result: object) -> None:
        self._release_ionization_busy(generation)
        try:
            if generation != self._generation:
                self._drain_pending_ionization()
                return
            if not isinstance(result, dict):
                self._on_ionization_failed(generation, "bad result")
                return
            self._clear_ionization_tooltips()
            self._val_logd.setText(_fmt_num(float(result["logd"]), 2))
            pkas = result.get("pka_values") or ()
            pka_tuple = tuple(pkas) if isinstance(pkas, (list, tuple)) else ()
            if not pka_tuple:
                self._set_ionization_error(_PKA_CALC_FAILED)
                self._drain_pending_ionization()
                return
            self._val_pka.setText(
                _fmt_pka(pka_tuple, approx=bool(result.get("pka_approx")), pending=False)
            )
            self._val_ab_mps.setText(_fmt_num(float(result["ab_mps"]), 2))
            self._val_cns_mpo.setText(_fmt_num(float(result["cns_mpo"]), 2))
            self._drain_pending_ionization()
        except Exception:
            logger.exception("applying sketcher ionization results failed")
            self._set_ionization_error(_PKA_CALC_FAILED)
            self._drain_pending_ionization()

    def _on_ionization_failed(self, generation: int, msg: str) -> None:
        self._release_ionization_busy(generation)
        if generation != self._generation:
            self._drain_pending_ionization()
            return
        if msg == "cancelled":
            self._drain_pending_ionization()
            return
        self._set_ionization_error(msg or _PKA_CALC_FAILED)
        self._drain_pending_ionization()
