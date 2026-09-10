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

"""Background EasyDock job: table ligands → scores and packed poses."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..confs_codec import pack_confs_cell
from ..easydock_backend import (
    EasyDockParams,
    combine_pose_mols,
    dock_mol,
    ensure_easydock_stack_ready,
    pose_table_props,
)
from .process_pool_utils import should_terminate_process_pool
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)

PROGRESS_LABEL = "Dock"


class EasyDockWorker(QRunnable):
    """Dock each ``(oid, mol_blob)`` with EasyDock; emit scores and packed ``confs`` cells."""

    def __init__(
        self,
        items: list[tuple[int, bytes]],
        params: EasyDockParams,
        signals: WorkerSignals,
        *,
        write_poses: bool = True,
        sdf_path: str | None = None,
        cancel_event: threading.Event | None = None,
    ):
        super().__init__()
        self.items = list(items)
        self.params = params
        self.signals = signals
        self.write_poses = bool(write_poses)
        self.sdf_path = (sdf_path or "").strip() or None
        self.cancel_event = cancel_event

    def run(self) -> None:
        err = ensure_easydock_stack_ready()
        if err:
            try:
                self.signals.easydock_failed.emit(err)
            except Exception:
                logger.exception("easydock_failed emit failed")
            return
        total = max(len(self.items), 1)
        rows: list[tuple] = []
        sdf_mols: list[Chem.Mol] = []
        cancelled = False
        try:
            self.signals.tool_progress.emit(PROGRESS_LABEL, 0, total)
        except Exception:
            pass
        for i, (oid, blob) in enumerate(self.items):
            if should_terminate_process_pool(self.cancel_event):
                cancelled = True
                break
            try:
                mol = Chem.Mol(blob) if blob else None
            except Exception:
                mol = None
            if mol is None or mol.GetNumAtoms() == 0:
                rows.append((int(oid), "", pack_confs_cell({"ok": False, "err": "no mol"}, None), []))
                self._progress(i + 1, total)
                continue
            mol.SetProp("_Name", str(oid))
            try:
                hit = dock_mol(mol, self.params, cancel_event=self.cancel_event)
            except Exception:
                logger.exception("dock_mol failed for oid=%s", oid)
                rows.append(
                    (int(oid), "", pack_confs_cell({"ok": False, "err": "dock failed"}, None), [])
                )
                self._progress(i + 1, total)
                continue
            if hit.error == "cancelled" or should_terminate_process_pool(self.cancel_event):
                cancelled = True
                break
            score_txt = "" if hit.score is None else f"{hit.score:.3f}"
            packed = ""
            combined = combine_pose_mols(list(hit.poses)) if self.write_poses else None
            if self.write_poses:
                meta = {
                    "ok": bool(combined is not None),
                    "n_requested": int(self.params.n_poses),
                    "n_kept": int(combined.GetNumConformers()) if combined is not None else 0,
                    "ff": str(self.params.engine),
                    "e_min_kcal": hit.score,
                    "err": hit.error or "",
                    "op": "easydock",
                }
                packed = pack_confs_cell(meta, combined)
            sdf_mols.extend(hit.poses)
            rows.append((int(oid), score_txt, packed, _pose_payloads(int(oid), hit.poses)))
            self._progress(i + 1, total)
        if self.sdf_path and sdf_mols and not cancelled:
            try:
                self._write_sdf(sdf_mols)
            except OSError:
                logger.exception("EasyDock SDF write failed: %s", self.sdf_path)
        emit_partial_results_if_cancelled(self.signals, PROGRESS_LABEL, len(rows), total, cancelled)
        try:
            self.signals.easydock_finished.emit(rows)
        except Exception:
            logger.exception("easydock_finished emit failed")

    def _progress(self, done: int, total: int) -> None:
        try:
            self.signals.tool_progress.emit(PROGRESS_LABEL, int(done), int(total))
        except Exception:
            pass

    def _write_sdf(self, mols: list[Chem.Mol]) -> None:
        from rdkit.Chem import SDWriter

        writer = SDWriter(self.sdf_path)
        try:
            for mol in mols:
                if mol is None:
                    continue
                n = int(mol.GetNumConformers())
                if n <= 1:
                    writer.write(mol)
                    continue
                for cid in range(n):
                    writer.write(mol, confId=cid)
        finally:
            writer.close()


def _pose_payloads(oid: int, poses) -> list[tuple[bytes, dict[str, str]]]:
    """Serialize each pose as ``(mol_blob, property_dict)`` for the results table."""
    items: list[tuple[bytes, dict[str, str]]] = []
    for i, pose in enumerate(poses or (), start=1):
        if pose is None:
            continue
        props = pose_table_props(pose)
        props.setdefault("Parent OID", str(oid))
        props.setdefault("mode", str(i))
        try:
            blob = pose.ToBinary()
        except Exception:
            continue
        items.append((blob, props))
    return items
