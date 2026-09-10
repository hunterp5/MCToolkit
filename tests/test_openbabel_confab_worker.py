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

"""Systematic Confab worker writeback with a mocked generator."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.openbabel_confab import SystematicConfParams
from molmanager.workers.openbabel_confab_worker import SystematicConformerWorker
from molmanager.workers.signals import WorkerSignals


def _ethanol() -> Chem.Mol:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == 0
    return mol


def test_systematic_worker_emits_packed_confs(qapp, monkeypatch):  # noqa: ARG001
    mol = _ethanol()

    def _fake_run(src, params, cancel_event=None):
        out = Chem.Mol(src)
        meta = {
            "ok": True,
            "n_requested": int(params.num_confs),
            "n_kept": int(out.GetNumConformers()),
            "ff": "MMFF94",
            "op": "confab",
        }
        return out, meta

    monkeypatch.setattr(
        "molmanager.workers.openbabel_confab_worker.ensure_openbabel_confab_ready",
        lambda _p="": None,
    )
    monkeypatch.setattr(
        "molmanager.workers.openbabel_confab_worker.run_systematic_conformer_generation",
        _fake_run,
    )
    sig = WorkerSignals()
    captured: list = []
    sig.conformers_finished.connect(captured.append)
    worker = SystematicConformerWorker(
        [(3, mol)],
        SystematicConfParams(num_confs=8),
        sig,
    )
    worker.run()
    assert captured
    oid, out_mol, cell = captured[0][0]
    assert oid == 3
    assert out_mol is not None
    assert out_mol.GetNumConformers() >= 1
    assert "confab" in cell or "n_kept" in cell


def test_systematic_worker_missing_openbabel(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        "molmanager.workers.openbabel_confab_worker.ensure_openbabel_confab_ready",
        lambda _p="": "Open Babel is required",
    )
    sig = WorkerSignals()
    captured: list = []
    sig.conformers_finished.connect(captured.append)
    worker = SystematicConformerWorker(
        [(1, _ethanol())],
        SystematicConfParams(),
        sig,
    )
    worker.run()
    assert captured
    oid, out_mol, cell = captured[0][0]
    assert oid == 1
    assert out_mol is None
    assert "openbabel_unavailable" in cell
