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

"""EasyDock worker writeback with a mocked engine."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.easydock_backend import EasyDockHit, EasyDockParams
from molmanager.workers.easydock_worker import EasyDockWorker
from molmanager.workers.signals import WorkerSignals


def _ethanol_blob() -> bytes:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == 0
    return mol.ToBinary()


def test_easydock_worker_emits_score_and_confs(qapp, monkeypatch):  # noqa: ARG001
    pose = Chem.Mol(Chem.Mol(_ethanol_blob()))

    def _fake_dock(mol, params, cancel_event=None):
        return EasyDockHit(-7.25, (pose,), error=None)

    monkeypatch.setattr("molmanager.workers.easydock_worker.dock_mol", _fake_dock)
    monkeypatch.setattr(
        "molmanager.workers.easydock_worker.ensure_easydock_stack_ready", lambda: None
    )
    sig = WorkerSignals()
    captured: list = []
    sig.easydock_finished.connect(captured.append)
    worker = EasyDockWorker(
        [(1, _ethanol_blob())],
        EasyDockParams(receptor_pdbqt="rec.pdbqt"),
        sig,
        write_poses=True,
    )
    worker.run()
    assert captured
    rows = captured[0]
    assert rows[0][0] == 1
    assert rows[0][1] == "-7.250"
    assert rows[0][2]
    assert len(rows[0]) >= 4
    assert rows[0][3]
    blob, props = rows[0][3][0]
    assert blob
    assert props.get("Parent OID") == "1"
    assert props.get("mode") == "1"


def test_easydock_worker_skips_poses_when_unchecked(qapp, monkeypatch):  # noqa: ARG001
    pose = Chem.Mol(Chem.Mol(_ethanol_blob()))

    def _fake_dock(mol, params, cancel_event=None):
        return EasyDockHit(-1.0, (pose,), error=None)

    monkeypatch.setattr("molmanager.workers.easydock_worker.dock_mol", _fake_dock)
    monkeypatch.setattr(
        "molmanager.workers.easydock_worker.ensure_easydock_stack_ready", lambda: None
    )
    sig = WorkerSignals()
    captured: list = []
    sig.easydock_finished.connect(captured.append)
    worker = EasyDockWorker(
        [(2, _ethanol_blob())],
        EasyDockParams(receptor_pdbqt="rec.pdbqt"),
        sig,
        write_poses=False,
    )
    worker.run()
    assert captured[0][0][1] == "-1.000"
    assert captured[0][0][2] == ""
    assert captured[0][0][3]
