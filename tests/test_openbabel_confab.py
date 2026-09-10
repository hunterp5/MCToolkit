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

"""Open Babel Confab backend (no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.openbabel_confab import (
    SystematicConfParams,
    apply_sdf_conformers,
    confab_cli_command,
    ensure_openbabel_confab_ready,
    python_confab_available,
    run_systematic_conformer_generation,
)


def _ethanol_confs(n: int = 2) -> Chem.Mol:
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    cids = AllChem.EmbedMultipleConfs(mol, n, randomSeed=7)
    assert cids
    return mol


def test_confab_cli_command_includes_cutoffs_and_original():
    params = SystematicConfParams(
        num_confs=25,
        rmsd_cutoff=0.75,
        energy_cutoff=12.5,
        include_original=True,
    )
    cmd = confab_cli_command("obabel", Path("in.sdf"), Path("out.sdf"), params)
    assert cmd[:5] == ["obabel", "in.sdf", "-O", "out.sdf", "--confab"]
    assert "--conf" in cmd and "25" in cmd
    assert "--rcutoff" in cmd and "0.75" in cmd
    assert "--ecutoff" in cmd and "12.5" in cmd
    assert "--original" in cmd


def test_ensure_openbabel_confab_ready_missing(monkeypatch):
    monkeypatch.setattr("molmanager.openbabel_confab.python_confab_available", lambda: False)
    monkeypatch.setattr("molmanager.openbabel_confab.resolve_obabel_executable", lambda _p="": None)
    err = ensure_openbabel_confab_ready()
    assert err is not None
    assert "Open Babel" in err


def test_pip_openbabel_is_default_and_ready():
    from molmanager.bundled_paths import default_external_executable, pip_openbabel_executable

    exe = pip_openbabel_executable()
    if exe is None:
        pytest.skip("openbabel wheel not installed")
    assert exe.is_file()
    assert default_external_executable("obabel") == str(exe)
    assert python_confab_available() is True
    assert ensure_openbabel_confab_ready(str(exe)) is None


def test_iter_sdf_mols_reads_molblock_records():
    from molmanager.openbabel_confab import iter_sdf_mols

    src = _ethanol_confs(2)
    sdf = "".join(
        Chem.MolToMolBlock(src, confId=int(cid)).rstrip("\n") + "\n$$$$\n"
        for cid in range(src.GetNumConformers())
    )
    mols = iter_sdf_mols(sdf)
    assert len(mols) == 2
    assert all(m.GetNumConformers() >= 1 for m in mols)
    src = _ethanol_confs(2)
    singles: list[Chem.Mol] = []
    for conf in src.GetConformers():
        one = Chem.Mol(src)
        one.RemoveAllConformers()
        one.AddConformer(Chem.Conformer(conf), assignId=True)
        singles.append(one)
    template = Chem.Mol(src)
    template.RemoveAllConformers()
    out = apply_sdf_conformers(template, singles)
    assert out is not None
    assert out.GetNumConformers() == 2
    assert out.GetNumAtoms() == src.GetNumAtoms()


def test_run_systematic_empty_mol():
    out, meta = run_systematic_conformer_generation(Chem.Mol(), SystematicConfParams())
    assert out is None
    assert meta.get("ok") is False
    assert "empty" in (meta.get("err") or "").lower()


def test_run_systematic_uses_confab_sdf(monkeypatch):
    src = _ethanol_confs(2)
    blocks = [Chem.MolToMolBlock(src, confId=int(cid)) for cid in range(src.GetNumConformers())]
    sdf = "".join(b if b.endswith("$$$$\n") else b.rstrip("\n") + "\n$$$$\n" for b in blocks)
    monkeypatch.setattr(
        "molmanager.openbabel_confab.ensure_openbabel_confab_ready", lambda _p="": None
    )
    monkeypatch.setattr("molmanager.openbabel_confab._run_confab", lambda _sdf, _params: sdf)
    out, meta = run_systematic_conformer_generation(
        Chem.MolFromSmiles("CCO"), SystematicConfParams(num_confs=4)
    )
    assert out is not None
    assert meta.get("ok") is True
    assert out.GetNumConformers() == 2
    assert meta.get("n_kept") == 2
    assert meta.get("op") == "confab"
    assert meta.get("ff") == "MMFF94"
