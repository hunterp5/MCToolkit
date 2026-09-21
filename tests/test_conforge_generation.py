# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""CONFORGE backend (no Qt)."""

from __future__ import annotations

from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from mctoolkit.conformers.conforge_generation import (
    ConforgeParams,
    confgen_cli_command,
    ensure_conforge_ready,
    normalize_conforge_mode,
    normalize_conforge_preset,
    python_conforge_available,
    run_conforge_generation,
)


def _ethanol_3d() -> Chem.Mol:
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    assert AllChem.EmbedMolecule(mol, randomSeed=7) == 0
    return mol


def test_normalize_conforge_preset_and_mode():
    assert normalize_conforge_preset("medium set diverse") == "MEDIUM_SET_DIVERSE"
    assert normalize_conforge_preset("nope") == "MEDIUM_SET_DIVERSE"
    assert normalize_conforge_mode("stochastic") == "STOCHASTIC"
    assert normalize_conforge_mode("x") == "AUTO"


def test_confgen_cli_command_includes_cutoffs_and_include_input():
    params = ConforgeParams(
        num_confs=25,
        rmsd_cutoff=0.75,
        energy_window=12.5,
        mode="SYSTEMATIC",
        preset="SMALL_SET_DENSE",
        timeout_s=90,
        include_input=True,
        from_scratch=False,
    )
    cmd = confgen_cli_command("confgen", Path("in.sdf"), Path("out.sdf"), params)
    assert cmd[:5] == ["confgen", "-i", "in.sdf", "-o", "out.sdf"]
    assert "-C" in cmd and "SMALL_SET_DENSE" in cmd
    assert "-m" in cmd and "SYSTEMATIC" in cmd
    assert "-e" in cmd and "12.5" in cmd
    assert "-r" in cmd and "0.75" in cmd
    assert "-n" in cmd and "25" in cmd
    assert "-T" in cmd and "90" in cmd
    assert "-u" in cmd
    assert "-S" in cmd and "0" in cmd


def test_ensure_conforge_ready_reports_missing(monkeypatch):
    monkeypatch.setattr(
        "mctoolkit.conformers.conforge_generation.python_conforge_available", lambda: False
    )
    monkeypatch.setattr(
        "mctoolkit.conformers.conforge_generation.resolve_confgen_executable", lambda _p="": None
    )
    err = ensure_conforge_ready("")
    assert err is not None
    assert "boost" in err.lower()
    assert "github.com/molinfo-vienna/CDPKit" in err


def test_run_conforge_generation_merges_sdf(monkeypatch):
    mol = _ethanol_3d()
    block = Chem.MolToMolBlock(mol)
    sdf = block + "$$$$\n" + block + "$$$$\n"
    monkeypatch.setattr(
        "mctoolkit.conformers.conforge_generation.ensure_conforge_ready", lambda _p="": None
    )
    monkeypatch.setattr(
        "mctoolkit.conformers.conforge_generation._run_conforge", lambda _sdf, _p: sdf
    )
    out, meta = run_conforge_generation(mol, ConforgeParams(num_confs=10))
    assert meta["ok"] is True
    assert meta["op"] == "conforge"
    assert out is not None
    assert out.GetNumConformers() >= 1


def test_run_conforge_generation_empty_mol():
    empty = Chem.Mol()
    out, meta = run_conforge_generation(empty, ConforgeParams())
    assert out is None
    assert meta["ok"] is False
    assert meta["err"] == "empty_molecule"


def test_python_conforge_available_is_bool():
    assert python_conforge_available() in {True, False}
