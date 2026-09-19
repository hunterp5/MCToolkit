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

"""Background H-bond / ProLIF overlay compute for the protein canvas."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, QRunnable, QTimer, Signal

from ..chem.molecule_conversion import copy_mol
from ..protein.hydrogen_bonds import HBOND_KIND_COMPLEX
from ..protein.protein_interactions import (
    compute_dock_pose_overlays,
    compute_viewer_interaction_overlays,
    prolif_available,
)
from .threadpool_access import start_runnable_on_app_pool

logger = logging.getLogger(__name__)


class InteractionOverlaySignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class InteractionOverlayWorker(QRunnable):
    def __init__(
        self,
        generation: int,
        jobs: list[tuple[str, str, str, int | None]],
        *,
        hbonds: bool,
        prolif: bool,
        signals: InteractionOverlaySignals,
        skip_sids: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._generation = generation
        self._jobs = jobs
        self._hbonds = hbonds
        self._prolif = prolif
        self._signals = signals
        self._skip_sids = skip_sids if skip_sids is not None else set()

    def run(self) -> None:
        out: dict[str, tuple[tuple, tuple]] = {}
        try:
            want_prolif = self._prolif and prolif_available()
            for sid, text, fmt, model in self._jobs:
                if sid in self._skip_sids:
                    continue
                out[sid] = compute_viewer_interaction_overlays(
                    text,
                    fmt,
                    model=model,
                    hbonds=self._hbonds,
                    prolif=want_prolif,
                )
        except Exception as exc:
            logger.debug("Protein viewer overlay worker failed", exc_info=True)
            self._signals.failed.emit(self._generation, str(exc) or type(exc).__name__)
            return
        self._signals.finished.emit(self._generation, out)


class DockPoseOverlayWorker(QRunnable):
    """Fingerprint one docked pose against polymer atoms (cached protein mol)."""

    def __init__(
        self,
        generation: int,
        protein_text: str,
        protein_fmt: str,
        ligand_mol,
        model: int | None,
        *,
        hbonds: bool,
        prolif: bool,
        signals: InteractionOverlaySignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._generation = generation
        self._protein_text = protein_text
        self._protein_fmt = protein_fmt
        self._ligand_mol = ligand_mol
        self._model = model
        self._hbonds = hbonds
        self._prolif = prolif
        self._signals = signals

    def run(self) -> None:
        try:
            want_prolif = self._prolif and prolif_available()
            pair = compute_dock_pose_overlays(
                self._protein_text,
                self._protein_fmt,
                self._ligand_mol,
                model=self._model,
                hbonds=self._hbonds,
                prolif=want_prolif,
            )
        except Exception as exc:
            logger.debug("Dock-pose overlay worker failed", exc_info=True)
            self._signals.failed.emit(self._generation, str(exc) or type(exc).__name__)
            return
        self._signals.finished.emit(self._generation, pair)


def start_interaction_overlay_worker(app, worker: QRunnable) -> None:
    """Run inline under pytest; otherwise use the app thread pool."""
    if "pytest" in sys.modules:
        worker.run()
        return
    start_runnable_on_app_pool(app, worker)


class ProteinViewerOverlayJobMixin:
    """Push the 3D model first; compute H-bond/ProLIF cylinders off the GUI thread."""

    def _invalidate_hbonds(self, structure_id: str | None = None) -> None:
        gen = int(getattr(self, "_overlay_job_gen", 0)) + 1
        self._overlay_job_gen = gen
        slot_gen = getattr(self, "_overlay_slot_gen", None)
        if slot_gen is None:
            slot_gen = {}
            self._overlay_slot_gen = slot_gen
        if structure_id is None:
            for slot in self._slots:
                slot_gen[slot.structure_id] = gen
            pending = getattr(self, "_overlay_pending_sids", None)
            if pending is not None:
                pending.clear()
            live = {slot.structure_id for slot in self._slots}
            self._overlay_skip_sids().difference_update(live)
        else:
            slot_gen[structure_id] = gen
            pending = getattr(self, "_overlay_pending_sids", None)
            if pending is not None:
                pending.discard(structure_id)
            self._overlay_skip_sids().discard(structure_id)
        super()._invalidate_hbonds(structure_id)
        if getattr(self, "_dock_pose_payload", None):
            self._invalidate_dock_pose_overlay()
            if self._interaction_overlay_active():
                self._schedule_dock_pose_overlay_job()

    def _ensure_hbond_cache(self) -> None:
        self._schedule_interaction_overlay_job()

    def _ensure_prolif_cache(self) -> None:
        self._schedule_interaction_overlay_job()

    def _interaction_overlay_caches_ready(self) -> bool:
        if not self._interaction_overlay_active():
            return True
        want_h = bool(self._hbond_kinds_enabled())
        want_p = bool(
            self._prolif_families_enabled() or HBOND_KIND_COMPLEX in self._hbond_kinds_enabled()
        )
        cache = getattr(self, "_prolif_cache", None)
        if cache is None:
            cache = {}
        for slot in self._slots:
            if want_h and slot.structure_id not in self._hbond_cache:
                return False
            if want_p and slot.structure_id not in cache:
                return False
        return True

    def _hbond_payload_for_structure_push(self) -> dict:
        """Return overlay cylinders if cached; otherwise show the structure first."""
        if self._interaction_overlay_active():
            self._schedule_interaction_overlay_job()
        return self._hbond_overlay_payload()

    def _push_hbonds(self) -> None:
        if self._interaction_overlay_active():
            self._schedule_interaction_overlay_job()
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _overlay_skip_sids(self) -> set[str]:
        skip = getattr(self, "_overlay_skip_sid_set", None)
        if skip is None:
            skip = set()
            self._overlay_skip_sid_set = skip
        return skip

    def _drop_overlay_structures(self, sids) -> None:
        """Stop overlay work for removed Manager structures."""
        dead = {str(sid) for sid in (sids or []) if sid}
        if not dead:
            return
        self._overlay_skip_sids().update(dead)
        pending = getattr(self, "_overlay_pending_sids", None)
        if pending is not None:
            pending.difference_update(dead)
        inflight = getattr(self, "_overlay_inflight_sids", None)
        if inflight is not None:
            inflight.difference_update(dead)
        slot_gen = getattr(self, "_overlay_slot_gen", None)
        if slot_gen is None:
            slot_gen = {}
            self._overlay_slot_gen = slot_gen
        gen = int(getattr(self, "_overlay_job_gen", 0)) + 1
        self._overlay_job_gen = gen
        cache = getattr(self, "_prolif_cache", None)
        if cache is None:
            cache = {}
            self._prolif_cache = cache
        for sid in dead:
            slot_gen[sid] = gen
            self._hbond_cache.pop(sid, None)
            cache.pop(sid, None)

    def _schedule_interaction_overlay_job(self) -> None:
        """Queue overlay compute after the canvas has a chance to paint."""
        if "pytest" in sys.modules:
            self._start_interaction_overlay_job()
            return
        timer = getattr(self, "_overlay_delay_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._start_interaction_overlay_job)
            self._overlay_delay_timer = timer
        timer.start()

    def _start_interaction_overlay_job(self) -> None:
        want_h = bool(self._hbond_kinds_enabled())
        want_p = bool(
            self._prolif_families_enabled() or HBOND_KIND_COMPLEX in self._hbond_kinds_enabled()
        )
        if not want_h and not want_p:
            return
        if getattr(self, "_overlay_worker_running", False):
            self._overlay_reschedule = True
            return
        if getattr(self, "_prolif_cache", None) is None:
            self._prolif_cache = {}
        skip = self._overlay_skip_sids()
        jobs: list[tuple[str, str, str, int | None]] = []
        for slot in self._slots:
            sid = slot.structure_id
            if sid in skip:
                continue
            need_h = want_h and sid not in self._hbond_cache
            need_p = want_p and sid not in self._prolif_cache
            if need_h or need_p:
                jobs.append((sid, slot.text, slot.fmt, self._slot_model_index(slot)))
        if not jobs:
            return
        pending = getattr(self, "_overlay_pending_sids", None)
        if pending is None:
            pending = set()
            self._overlay_pending_sids = pending
        jobs = [item for item in jobs if item[0] not in pending]
        if not jobs:
            return
        gen = int(getattr(self, "_overlay_job_gen", 0))
        signals = getattr(self, "_interaction_overlay_signals", None)
        if signals is None:
            signals = InteractionOverlaySignals(self)
            signals.finished.connect(self._on_interaction_overlay_finished)
            signals.failed.connect(self._on_interaction_overlay_failed)
            self._interaction_overlay_signals = signals
        job_ids = {item[0] for item in jobs}
        skip.difference_update(job_ids)
        pending.update(job_ids)
        self._overlay_inflight_sids = set(job_ids)
        names = ", ".join(slot.name for slot in self._slots if slot.structure_id in job_ids)
        self.append_log(f"Computing interaction overlays for {names}…")
        self._overlay_worker_running = True
        self._overlay_reschedule = False
        worker = InteractionOverlayWorker(
            gen,
            jobs,
            hbonds=want_h,
            prolif=want_p,
            signals=signals,
            skip_sids=skip,
        )
        start_interaction_overlay_worker(self.parent(), worker)

    def _receptor_slot_for_dock_pose(self):
        slot = self._active_slot()
        if slot is not None and any(row.spec.kind == "polymer" for row in slot.rows):
            return slot
        for candidate in self._slots:
            if any(row.spec.kind == "polymer" for row in candidate.rows):
                return candidate
        return slot

    def _enable_protein_ligand_interactions_for_dock_pose(self) -> None:
        kinds = {row.spec.kind for row in self._rows}
        if "polymer" not in kinds:
            return
        acts = [self._act_hbond_ligand, *self._protein_ligand_interaction_actions()]
        for act in acts:
            if act is None or act.isChecked():
                continue
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)

    def _invalidate_dock_pose_overlay(self) -> None:
        self._dock_pose_overlay = None
        self._dock_pose_overlay_gen = int(getattr(self, "_dock_pose_overlay_gen", 0)) + 1

    def _on_dock_pose_changed(self) -> None:
        self._invalidate_dock_pose_overlay()
        if getattr(self, "_dock_pose_payload", None):
            self._enable_protein_ligand_interactions_for_dock_pose()
            if self._interaction_overlay_active():
                self._schedule_dock_pose_overlay_job()
        if self._interaction_overlay_active():
            self._push_hbonds()

    def _schedule_dock_pose_overlay_job(self) -> None:
        mol = getattr(self, "_dock_pose_mol", None)
        if mol is None or not self._dock_pose_payload:
            return
        want_h = bool(self._hbond_kinds_enabled())
        want_p = bool(
            self._prolif_families_enabled() or HBOND_KIND_COMPLEX in self._hbond_kinds_enabled()
        )
        if not want_h and not want_p:
            return
        slot = self._receptor_slot_for_dock_pose()
        if slot is None:
            return
        if not any(row.spec.kind == "polymer" for row in slot.rows):
            return
        lig = copy_mol(mol) or mol
        gen = int(getattr(self, "_dock_pose_overlay_gen", 0))
        signals = getattr(self, "_dock_pose_overlay_signals", None)
        if signals is None:
            signals = InteractionOverlaySignals(self)
            signals.finished.connect(self._on_dock_pose_overlay_finished)
            signals.failed.connect(self._on_dock_pose_overlay_failed)
            self._dock_pose_overlay_signals = signals
        worker = DockPoseOverlayWorker(
            gen,
            slot.text,
            slot.fmt,
            lig,
            self._slot_model_index(slot),
            hbonds=want_h,
            prolif=want_p,
            signals=signals,
        )
        start_interaction_overlay_worker(self.parent(), worker)

    def _on_dock_pose_overlay_finished(self, generation: int, payload) -> None:
        if int(generation) != int(getattr(self, "_dock_pose_overlay_gen", 0)):
            return
        if not getattr(self, "_dock_pose_payload", None):
            return
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._dock_pose_overlay = ((), ())
        else:
            self._dock_pose_overlay = (payload[0] or (), payload[1] or ())
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _on_dock_pose_overlay_failed(self, generation: int, message: str) -> None:
        if int(generation) != int(getattr(self, "_dock_pose_overlay_gen", 0)):
            return
        if not getattr(self, "_dock_pose_payload", None):
            return
        self._dock_pose_overlay = ((), ())
        self.append_log(f"Pose interaction overlays failed: {message}")
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _finish_overlay_worker(self) -> None:
        inflight = getattr(self, "_overlay_inflight_sids", None)
        pending = getattr(self, "_overlay_pending_sids", None)
        if inflight is not None and pending is not None:
            pending.difference_update(inflight)
            inflight.clear()
        self._overlay_worker_running = False
        self._overlay_reschedule = False
        self._start_interaction_overlay_job()

    def _on_interaction_overlay_finished(self, generation: int, payload) -> None:
        pending = getattr(self, "_overlay_pending_sids", None)
        if not isinstance(payload, dict):
            self._finish_overlay_worker()
            return
        if getattr(self, "_prolif_cache", None) is None:
            self._prolif_cache = {}
        slot_gen = getattr(self, "_overlay_slot_gen", None) or {}
        live = {slot.structure_id for slot in self._slots}
        skip = self._overlay_skip_sids()
        n_h = 0
        n_p = 0
        applied = False
        for sid, pair in payload.items():
            if pending is not None:
                pending.discard(sid)
            if sid not in live or sid in skip:
                continue
            if int(slot_gen.get(sid, 0)) > int(generation):
                continue
            if not isinstance(pair, tuple) or len(pair) != 2:
                continue
            hbonds, contacts = pair
            self._hbond_cache[sid] = hbonds or ()
            self._prolif_cache[sid] = contacts or ()
            n_h += len(hbonds or ())
            n_p += len(contacts or ())
            applied = True
        self._finish_overlay_worker()
        if not applied:
            return
        self.append_log(f"Interaction overlays ready ({n_h} H-bond(s), {n_p} ProLIF contact(s)).")
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _on_interaction_overlay_failed(self, generation: int, message: str) -> None:
        self._finish_overlay_worker()
        slot_gen = getattr(self, "_overlay_slot_gen", None) or {}
        if slot_gen and int(generation) < max(slot_gen.values(), default=0):
            return
        self.append_log(f"Interaction overlays failed: {message}")
