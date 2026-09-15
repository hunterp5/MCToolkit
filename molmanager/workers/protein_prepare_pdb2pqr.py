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

"""pdb2pqr / PROPKA protonation step for Protein Prepare."""

from __future__ import annotations

from pathlib import Path

from .protein_prepare_constants import _PDB2PQR_FF
from .protein_prepare_io import (
    _is_cif_path,
    _unlink_quiet,
    _write_text,
)


def pdb2pqr_argv(
    input_pdb: Path,
    output_pqr: Path,
    output_pdb: Path,
    *,
    ph: float,
    drop_water: bool = True,
    ligand_mol2: Path | None = None,
) -> list[str]:
    """CLI argv for pdb2pqr (AMBER names + PROPKA titration at *ph*)."""
    argv = [
        f"--ff={_PDB2PQR_FF}",
        f"--ffout={_PDB2PQR_FF}",
        "--keep-chain",
    ]
    if drop_water:
        argv.append("--drop-water")
    if ligand_mol2 is not None:
        argv.extend(["--ligand", str(ligand_mol2)])
    argv.extend(
        [
            "--titration-state-method=propka",
            f"--with-ph={float(ph):.1f}",
            "--pdb-output",
            str(output_pdb),
            "--log-level=ERROR",
            str(input_pdb),
            str(output_pqr),
        ]
    )
    return argv


def _run_pdb2pqr(
    input_pdb: Path,
    output_pqr: Path,
    output_pdb: Path,
    *,
    ph: float,
    drop_water: bool = True,
    ligand_mol2: Path | None = None,
) -> None:
    try:
        from pdb2pqr.main import run_pdb2pqr
    except Exception as exc:
        raise RuntimeError(
            "pdb2pqr is required for pH-based protonation. Install with: pip install pdb2pqr"
        ) from exc

    write_cif = _is_cif_path(output_pdb)
    write_cif_in = _is_cif_path(input_pdb)
    pdb_in = input_pdb
    pdb_out = output_pdb
    scratch_in: Path | None = None
    if write_cif:
        pdb_out = output_pdb.with_name(output_pdb.stem + ".pdb2pqr.pdb")
    if write_cif_in:
        from ..structure_components import _pdb_from_atoms, parse_structure_atoms

        scratch_in = input_pdb.with_name(input_pdb.stem + ".pdb2pqr_in.pdb")
        _write_text(
            scratch_in,
            _pdb_from_atoms(
                parse_structure_atoms(
                    input_pdb.read_text(encoding="utf-8", errors="replace"), "cif"
                )
            ),
        )
        pdb_in = scratch_in
    argv = pdb2pqr_argv(
        pdb_in,
        output_pqr,
        pdb_out,
        ph=ph,
        drop_water=drop_water,
        ligand_mol2=ligand_mol2,
    )
    try:
        run_pdb2pqr(argv)
    except SystemExit as exc:
        raise RuntimeError(f"pdb2pqr failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"pdb2pqr failed: {exc}") from exc
    finally:
        _unlink_quiet(scratch_in)
    if not pdb_out.is_file() or pdb_out.stat().st_size < 32:
        raise RuntimeError("pdb2pqr did not write a protonated structure file.")
    if write_cif:
        from ..structure_components import (
            parse_cif_chem_comp_atoms,
            parse_cif_chem_comp_bonds,
            pdb_to_mmcif,
        )

        src = ""
        if write_cif_in and input_pdb.is_file():
            src = input_pdb.read_text(encoding="utf-8", errors="replace")
        output_pdb.parent.mkdir(parents=True, exist_ok=True)
        _write_text(
            output_pdb,
            pdb_to_mmcif(
                pdb_out.read_text(encoding="utf-8", errors="replace"),
                data_name=output_pdb.stem,
                chem_atoms=parse_cif_chem_comp_atoms(src) if src else None,
                chem_bonds=parse_cif_chem_comp_bonds(src) if src else None,
            ),
        )
        _unlink_quiet(pdb_out)
