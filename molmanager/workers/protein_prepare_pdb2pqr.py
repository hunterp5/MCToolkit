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

import logging
from pathlib import Path

from .protein_prepare_constants import ResidueKey, _PDB2PQR_FF
from .protein_prepare_io import (
    _is_cif_fmt,
    _is_cif_path,
    _norm_key,
    _unlink_quiet,
    _write_text,
)

_BACKBONE_HEAVY = frozenset({"N", "CA", "C"})


class _Pdb2pqrLogCapture(logging.Handler):
    """Collect PDB2PQR ERROR/CRITICAL lines; the Python exception is often empty."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = (record.getMessage() or "").strip()
        except Exception:
            return
        if msg and msg.lower() != "giving up.":
            self.messages.append(msg)


def _exception_chain_message(exc: BaseException) -> str:
    texts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        if text and text not in {"0", "1"}:
            texts.append(text)
        current = current.__cause__ or current.__context__
    return texts[-1] if texts else ""


def _pdb2pqr_failure_message(exc: BaseException, capture: _Pdb2pqrLogCapture) -> str:
    detail = ""
    for msg in reversed(capture.messages):
        if msg:
            detail = msg
            break
    if not detail:
        detail = _exception_chain_message(exc)
    return f"pdb2pqr failed: {detail}" if detail else "pdb2pqr failed."


def drop_uncappable_polymer_residues(text: str, fmt: str) -> tuple[str, tuple[ResidueKey, ...]]:
    """Remove amino-acid residues that lack backbone N/CA/C (pdb2pqr cannot cap them)."""
    from ..structure_component_types import AMINO_ACIDS
    from ..structure_components import (
        delete_cif_residues,
        delete_pdb_residues,
        parse_structure_atoms,
    )

    names: dict[ResidueKey, set[str]] = {}
    resn_by: dict[ResidueKey, str] = {}
    for atom in parse_structure_atoms(text or "", fmt):
        key = _norm_key(atom.chain, atom.resi, atom.icode)
        resn_by[key] = (atom.resn or "").strip().upper()
        names.setdefault(key, set()).add((atom.name or "").strip().upper())
    drop = tuple(
        sorted(
            key
            for key, atom_names in names.items()
            if resn_by.get(key, "") in AMINO_ACIDS and not _BACKBONE_HEAVY.issubset(atom_names)
        )
    )
    if not drop:
        return text or "", ()
    keys = set(drop)
    if _is_cif_fmt(fmt):
        return delete_cif_residues(text, keys), drop
    return delete_pdb_residues(text, keys), drop


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
    pdb_text = pdb_in.read_text(encoding="utf-8", errors="replace")
    pdb_text, stubs = drop_uncappable_polymer_residues(pdb_text, "pdb")
    if stubs:
        if scratch_in is None:
            scratch_in = pdb_in.with_name(pdb_in.stem + ".pdb2pqr_in.pdb")
        _write_text(scratch_in, pdb_text)
        pdb_in = scratch_in
    argv = pdb2pqr_argv(
        pdb_in,
        output_pqr,
        pdb_out,
        ph=ph,
        drop_water=drop_water,
        ligand_mol2=ligand_mol2,
    )
    capture = _Pdb2pqrLogCapture()
    pqr_loggers: list[logging.Logger] = []
    try:
        from pdb2pqr.config import VERSION as _pqr_version

        pqr_loggers.append(logging.getLogger(f"PDB2PQR{_pqr_version}"))
    except Exception:
        pass
    pqr_loggers.append(logging.getLogger("pdb2pqr"))
    for logger in pqr_loggers:
        logger.addHandler(capture)
    try:
        run_pdb2pqr(argv)
    except SystemExit as exc:
        raise RuntimeError(_pdb2pqr_failure_message(exc, capture)) from exc
    except Exception as exc:
        raise RuntimeError(_pdb2pqr_failure_message(exc, capture)) from exc
    finally:
        for logger in pqr_loggers:
            logger.removeHandler(capture)
        _unlink_quiet(scratch_in)
    if not pdb_out.is_file() or pdb_out.stat().st_size < 32:
        raise RuntimeError("pdb2pqr did not write a protonated structure file.")
    if write_cif:
        from ..structure_components import (
            parse_cif_chem_comp_atoms,
            parse_cif_chem_comp_bonds,
            pdb_to_mmcif,
        )
        from ..structure_cif import repair_cif_hydrogen_chem_bonds

        src = ""
        if write_cif_in and input_pdb.is_file():
            src = input_pdb.read_text(encoding="utf-8", errors="replace")
        output_pdb.parent.mkdir(parents=True, exist_ok=True)
        cif_text = pdb_to_mmcif(
            pdb_out.read_text(encoding="utf-8", errors="replace"),
            data_name=output_pdb.stem,
            chem_atoms=parse_cif_chem_comp_atoms(src) if src else None,
            chem_bonds=parse_cif_chem_comp_bonds(src) if src else None,
        )
        _write_text(output_pdb, repair_cif_hydrogen_chem_bonds(cif_text))
        _unlink_quiet(pdb_out)
