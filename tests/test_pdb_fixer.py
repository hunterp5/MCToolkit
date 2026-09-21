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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""PDBFixer receptor preparation for docking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mctoolkit.workers.pdb_fixer_runtime import (
    PdbFixerRequest,
    _drop_internal_missing_residues,
    mp_prepare_pdb_for_docking,
    prepare_pdb_for_docking,
)


def test_drop_internal_missing_residues_keeps_terminal_gaps_only():
    fixer = MagicMock()
    chain0 = MagicMock()
    chain0_residues = [MagicMock() for _ in range(5)]
    chain0.residues.return_value = chain0_residues
    chain1 = MagicMock()
    chain1.residues.return_value = [MagicMock()]
    fixer.topology.chains.return_value = [chain0, chain1]
    fixer.missingResidues = {(0, 0): ["ALA"], (0, 3): ["GLY"], (0, 5): ["VAL"], (1, 0): ["MET"]}

    _drop_internal_missing_residues(fixer)

    assert (0, 0) in fixer.missingResidues
    assert (0, 3) not in fixer.missingResidues
    assert (0, 5) in fixer.missingResidues
    assert (1, 0) in fixer.missingResidues


def test_prepare_pdb_for_docking_missing_input(tmp_path):
    req = PdbFixerRequest(
        input_pdb_path=str(tmp_path / "missing.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    with pytest.raises(RuntimeError, match="Input PDB not found"):
        prepare_pdb_for_docking(req)


@patch("openmm.app.PDBFile")
@patch("pdbfixer.PDBFixer")
@patch("openmm.Platform.getPlatformByName")
def test_prepare_pdb_for_docking_runs_expected_steps(
    mock_get_platform, mock_fixer_cls, mock_pdb_file, tmp_path
):
    pytest.importorskip("openmm")
    in_path = tmp_path / "receptor.pdb"
    out_path = tmp_path / "receptor_prepared.pdb"
    in_path.write_text("ATOM\n", encoding="utf-8")

    fixer = MagicMock()
    chain = MagicMock()
    chain.residues.return_value = []
    fixer.topology.chains.return_value = [chain]
    fixer.missingResidues = {}
    mock_fixer_cls.return_value = fixer

    req = PdbFixerRequest(
        input_pdb_path=str(in_path),
        output_pdb_path=str(out_path),
    )
    prepare_pdb_for_docking(req)

    mock_get_platform.assert_called_once_with("CPU")
    mock_fixer_cls.assert_called_once_with(filename=str(in_path))
    assert fixer.platform is mock_get_platform.return_value
    fixer.findMissingResidues.assert_called_once()
    fixer.findNonstandardResidues.assert_called_once()
    fixer.replaceNonstandardResidues.assert_called_once()
    fixer.removeHeterogens.assert_called_once_with(keepWater=False)
    fixer.findMissingAtoms.assert_called_once()
    fixer.addMissingAtoms.assert_called_once()
    fixer.addMissingHydrogens.assert_called_once_with(7.0)
    mock_pdb_file.writeFile.assert_called_once()


def test_mp_prepare_pdb_for_docking_returns_error_message(tmp_path):
    req = PdbFixerRequest(
        input_pdb_path=str(tmp_path / "missing.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    ok, msg = mp_prepare_pdb_for_docking(req)
    assert ok is False
    assert "Input PDB not found" in msg


@patch("mctoolkit.workers.pdb_fixer_runtime.prepare_pdb_for_docking")
def test_mp_prepare_pdb_for_docking_success(mock_prepare, tmp_path):
    out_path = tmp_path / "receptor_prepared.pdb"
    req = PdbFixerRequest(
        input_pdb_path=str(tmp_path / "receptor.pdb"),
        output_pdb_path=str(out_path),
    )
    ok, msg = mp_prepare_pdb_for_docking(req)
    assert ok is True
    assert msg == str(out_path)
    mock_prepare.assert_called_once_with(req)


@patch("mctoolkit.workers.pdb_fixer_runtime.prepare_pdb_for_docking")
def test_mp_prepare_pdb_for_docking_uses_runtime_module(mock_prepare, tmp_path):
    """Subprocess entry must live in a PyQt-free module."""
    from mctoolkit.workers import pdb_fixer_runtime

    assert pdb_fixer_runtime.__name__.endswith("pdb_fixer_runtime")
    req = PdbFixerRequest(
        input_pdb_path=str(tmp_path / "receptor.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    mp_prepare_pdb_for_docking(req)
    mock_prepare.assert_called_once_with(req)
