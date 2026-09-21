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

"""Add explicit hydrogens dialog and core helper."""

from __future__ import annotations

import pytest

pytest.importorskip("rdkit")
pytest.importorskip("PySide6.QtWidgets")

from rdkit import Chem

from mctoolkit.chem.structure_hydrogens import add_explicit_hydrogens, remove_explicit_hydrogens
from mctoolkit.ui.dialogs.mol_tools import (
    AddExplicitHydrogensDialog,
    RemoveExplicitHydrogensDialog,
)


def test_add_explicit_hydrogens_helper_expands_implicit_h():
    mol = Chem.MolFromSmiles("C")
    assert mol is not None
    assert mol.GetNumAtoms() == 1

    out = add_explicit_hydrogens(mol)
    assert out is not None
    assert out.GetNumAtoms() > mol.GetNumAtoms()
    assert any(atom.GetAtomicNum() == 1 for atom in out.GetAtoms())


def test_add_explicit_hydrogens_dialog_defaults(qapp):  # noqa: ARG001
    dlg = AddExplicitHydrogensDialog(["Structure", "SMILES"], 2)
    src, only_sel, no_render = dlg.config()
    assert src == "Structure"
    assert only_sel is False
    assert no_render is False


def test_remove_explicit_hydrogens_helper_strips_explicit_h():
    mol = Chem.MolFromSmiles("C")
    assert mol is not None
    with_h = add_explicit_hydrogens(mol)
    assert with_h is not None
    assert with_h.GetNumAtoms() > mol.GetNumAtoms()

    out = remove_explicit_hydrogens(with_h)
    assert out is not None
    assert out.GetNumAtoms() == mol.GetNumAtoms()
    assert not any(atom.GetAtomicNum() == 1 for atom in out.GetAtoms())


def test_remove_explicit_hydrogens_dialog_defaults(qapp):  # noqa: ARG001
    dlg = RemoveExplicitHydrogensDialog(["Structure", "SMILES"], 2)
    src, only_sel, no_render = dlg.config()
    assert src == "Structure"
    assert only_sel is False
    assert no_render is False
