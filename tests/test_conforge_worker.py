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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""CONFORGE worker writeback with a mocked generator."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from mctoolkit.conformers.conforge_generation import ConforgeParams
from mctoolkit.workers.conforge_worker import ConforgeConformerWorker
from mctoolkit.workers.signals import WorkerSignals


def _ethanol() -> Chem.Mol:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == 0
    return mol


def test_conforge_worker_emits_packed_confs(qapp, monkeypatch):  # noqa: ARG001
    mol = _ethanol()

    def _fake_run(src, params, cancel_event=None):
        out = Chem.Mol(src)
        meta = {
            "ok": True,
            "n_requested": int(params.num_confs),
            "n_kept": int(out.GetNumConformers()),
            "ff": "MMFF94",
            "op": "conforge",
        }
        return out, meta

    monkeypatch.setattr(
        "mctoolkit.workers.conforge_worker.ensure_conforge_ready",
        lambda _p="": None,
    )
    monkeypatch.setattr(
        "mctoolkit.workers.conforge_worker.run_conforge_generation",
        _fake_run,
    )
    sig = WorkerSignals()
    captured: list = []
    sig.conformers_finished.connect(captured.append)
    worker = ConforgeConformerWorker(
        [(3, mol)],
        ConforgeParams(num_confs=8),
        sig,
    )
    worker.run()
    assert captured
    oid, out_mol, cell = captured[0][0]
    assert oid == 3
    assert out_mol is not None
    assert out_mol.GetNumConformers() >= 1
    assert "conforge" in cell or "n_kept" in cell


def test_conforge_worker_missing_backend(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        "mctoolkit.workers.conforge_worker.ensure_conforge_ready",
        lambda _p="": "CONFORGE is required",
    )
    sig = WorkerSignals()
    captured: list = []
    sig.conformers_finished.connect(captured.append)
    worker = ConforgeConformerWorker(
        [(1, _ethanol())],
        ConforgeParams(),
        sig,
    )
    worker.run()
    assert captured
    oid, out_mol, cell = captured[0][0]
    assert oid == 1
    assert out_mol is None
    assert cell.get("err") == "conforge_unavailable"
