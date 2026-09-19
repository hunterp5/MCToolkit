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

"""Export and table expansion helpers for generated conformer ensembles."""

from __future__ import annotations

from pathlib import Path

from rdkit import Chem


def iter_single_conformer_mols(mol: Chem.Mol) -> list[Chem.Mol]:
    """Split a multi-conformer molecule into one RDKit mol per conformer."""
    if mol is None or mol.GetNumConformers() == 0:
        return []
    out: list[Chem.Mol] = []
    for cid in range(mol.GetNumConformers()):
        try:
            single = Chem.Mol(mol)
            conf = Chem.Conformer(mol.GetConformer(int(cid)))
            single.RemoveAllConformers()
            single.AddConformer(conf, assignId=True)
            out.append(single)
        except Exception:
            continue
    return out


def write_conformer_results_to_sdf(
    path: str | Path,
    results: list[tuple[int, Chem.Mol | None, str]],
) -> int:
    """
    Write generated conformers to an SDF file.

    Each kept conformer becomes one structure record named ``oid{parent}_conf{n}``.
    Returns the number of structures written.
    """
    out_path = Path(path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(out_path))
    written = 0
    try:
        for oid, mol, _cell in results:
            if mol is None:
                continue
            for conf_i, cm in enumerate(iter_single_conformer_mols(mol)):
                try:
                    cm.SetProp("_Name", f"oid{int(oid)}_conf{conf_i + 1}")
                except Exception:
                    pass
                writer.write(cm)
                written += 1
    finally:
        writer.close()
    return written
