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

"""Scientific QC helpers for Protein Viewer Prepare (altlocs, waters, pocket)."""

from __future__ import annotations

from collections import defaultdict

ResidueKey = tuple[str, str, str]

_TITRATABLE = {
    "HIS",
    "HID",
    "HIE",
    "HIP",
    "ASP",
    "ASH",
    "GLU",
    "GLH",
    "CYS",
    "CYM",
    "LYS",
    "LYN",
    "TYR",
    "TYM",
}
_WATER_CUTOFF = 3.5
_POCKET_TITRATION_CUTOFF = 5.0
_LOOP_LIGAND_CUTOFF = 8.0
_MAX_QC_ROWS = 16
_CIF_SEQUENCE_LOOP_PREFIXES = (
    "_entity_poly_seq.",
    "_struct_asym.",
    "_pdbx_poly_seq_scheme.",
)


def _norm_key(chain: str, resi: str, icode: str) -> ResidueKey:
    from ..protein.structure_components import _norm_chain

    return (_norm_chain(chain), str(resi or "").strip() or "0", str(icode or "").strip())


def _atom_key3(atom) -> ResidueKey:
    return _norm_key(atom.chain, atom.resi, atom.icode)


def _is_hydrogen(atom) -> bool:
    elem = (atom.elem or "").upper()
    name = (atom.name or "").strip().upper()
    return elem in {"H", "D"} or name in {"H", "D"} or name.startswith("H") and elem == "H"


def _dist_sq(a, b) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return dx * dx + dy * dy + dz * dz


def apply_highest_occupancy_altlocs(text: str, fmt: str) -> tuple[str, tuple[str, ...]]:
    """Keep the highest-occupancy altloc for each atom; flag disordered residues."""
    from ..protein.structure_components import (
        atoms_to_mmcif,
        attach_cif_chem_comp,
        parse_cif_chem_comp_atoms,
        parse_cif_chem_comp_bonds,
        parse_structure_atoms,
    )

    fmt_l = (fmt or "pdb").lower()
    atoms = parse_structure_atoms(text or "", fmt_l, include_altlocs=True)
    if not atoms:
        return text or "", ()
    grouped: dict[tuple[str, str, str, str], list] = defaultdict(list)
    for atom in atoms:
        grouped[(_atom_key3(atom)[0], _atom_key3(atom)[1], _atom_key3(atom)[2], atom.name)].append(
            atom
        )
    chosen: list = []
    disordered: list[str] = []
    seen_res: set[ResidueKey] = set()
    for key, copies in grouped.items():
        alts = {a.altloc or "?" for a in copies}
        best = max(
            copies,
            key=lambda a: (
                float(a.occupancy),
                2 if not a.altloc else 1 if a.altloc in {"A", "1"} else 0,
            ),
        )
        chosen.append(best)
        res_key = key[:3]
        if len(copies) > 1 and res_key not in seen_res:
            seen_res.add(res_key)
            disordered.append(
                f"{key[0]}:{copies[0].resn}{key[1]}{key[2]} altlocs={''.join(sorted(alts))}"
            )
    notes = tuple(disordered[:_MAX_QC_ROWS])
    if len(chosen) == len(atoms):
        return text or "", notes
    if fmt_l in {"cif", "mmcif"}:
        rebuilt = atoms_to_mmcif(chosen)
        rebuilt = attach_cif_chem_comp(
            rebuilt,
            parse_cif_chem_comp_atoms(text),
            parse_cif_chem_comp_bonds(text),
        )
        return _attach_cif_polymer_sequence(rebuilt, text), notes
    return _rewrite_pdb_altlocs(text or "", chosen), notes


def _attach_cif_polymer_sequence(dest: str, source: str) -> str:
    """Copy SEQRES-equivalent mmCIF loops onto an atom-only rewrite."""
    from ..protein.structure_cif import _cif_quote, _parse_cif_loops

    chunks: list[str] = []
    for tags, rows in _parse_cif_loops(source or ""):
        if not tags or not any(
            tag.lower().startswith(prefix) for tag in tags for prefix in _CIF_SEQUENCE_LOOP_PREFIXES
        ):
            continue
        chunks.append("loop_")
        chunks.extend(tags)
        for row in rows:
            chunks.append(" ".join(_cif_quote(cell) for cell in row))
        chunks.append("#")
    if not chunks:
        return dest or ""
    return (dest or "").rstrip() + "\n" + "\n".join(chunks) + "\n"


def _rewrite_pdb_altlocs(text: str, chosen) -> str:
    from ..protein.structure_components import _pdb_residue_key

    winners: set[tuple[str, str, str, str, str]] = set()
    for atom in chosen:
        winners.add((_atom_key3(atom)[0], atom.resi, atom.icode, atom.name, atom.altloc))
    out: list[str] = []
    for line in text.splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec not in {"ATOM", "HETATM"}:
            out.append(line.rstrip())
            continue
        padded = line.ljust(80)
        raw = _pdb_residue_key(line)
        if raw is None:
            continue
        chain, resi, icode = raw
        name = padded[12:16].strip()
        alt = padded[16:17].strip()
        if (chain, resi, icode, name, alt) in winners:
            out.append(line.rstrip())
    if out and not any(ln.startswith("END") for ln in out):
        out.append("END")
    return "\n".join(out) + ("\n" if out else "")


def bridging_water_keys(
    text: str,
    fmt: str,
    ligand_keys: set[ResidueKey],
    *,
    cutoff: float = _WATER_CUTOFF,
    min_occupancy: float = 0.5,
    max_bfactor: float = 80.0,
) -> tuple[ResidueKey, ...]:
    """Waters whose oxygen is close to a ligand heavy atom, with decent occupancy."""
    from ..protein.structure_components import WATER_RESIDUES, parse_structure_atoms

    if not ligand_keys:
        return ()
    atoms = parse_structure_atoms(text or "", fmt)
    wanted = {_norm_key(*key) for key in ligand_keys}
    ligand = [a for a in atoms if _atom_key3(a) in wanted and not _is_hydrogen(a)]
    if not ligand:
        return ()
    cutoff_sq = float(cutoff) ** 2
    keep: set[ResidueKey] = set()
    for atom in atoms:
        if (atom.resn or "").upper() not in WATER_RESIDUES:
            continue
        if _is_hydrogen(atom):
            continue
        if atom.occupancy < float(min_occupancy):
            continue
        if atom.bfactor > float(max_bfactor) > 0 and atom.bfactor > 0:
            continue
        if any(_dist_sq(atom, lig) <= cutoff_sq for lig in ligand):
            keep.add(_atom_key3(atom))
    return tuple(sorted(keep))


def occupancy_warning_remarks(
    text: str,
    fmt: str,
    ligand_keys: set[ResidueKey],
    *,
    cutoff: float = _POCKET_TITRATION_CUTOFF,
) -> tuple[str, ...]:
    """Pocket residues that still have occupancy < 1 after altloc selection."""
    from ..protein.structure_components import parse_structure_atoms

    atoms = parse_structure_atoms(text or "", fmt)
    if not atoms or not ligand_keys:
        return ()
    wanted = {_norm_key(*key) for key in ligand_keys}
    ligand = [a for a in atoms if _atom_key3(a) in wanted and not _is_hydrogen(a)]
    if not ligand:
        return ()
    cutoff_sq = float(cutoff) ** 2
    flagged: dict[ResidueKey, str] = {}
    for atom in atoms:
        if atom.occupancy >= 0.999 or _is_hydrogen(atom):
            continue
        if not any(_dist_sq(atom, lig) <= cutoff_sq for lig in ligand):
            continue
        key = _atom_key3(atom)
        flagged.setdefault(key, f"{key[0]}:{atom.resn}{key[1]} occ={atom.occupancy:.2f}")
    return tuple(flagged[k] for k in sorted(flagged)[:_MAX_QC_ROWS])


def pocket_titration_remarks(
    protein_text: str,
    protein_fmt: str,
    ligand_text: str,
    ligand_fmt: str,
    ligand_keys: set[ResidueKey],
    *,
    cutoff: float = _POCKET_TITRATION_CUTOFF,
) -> tuple[str, ...]:
    """AMBER names of titratable residues within *cutoff* Å of the ligand."""
    from ..protein.structure_components import AMINO_ACIDS, parse_structure_atoms

    if not ligand_keys:
        return ()
    lig_atoms = [
        a
        for a in parse_structure_atoms(ligand_text or "", ligand_fmt)
        if _atom_key3(a) in {_norm_key(*k) for k in ligand_keys} and not _is_hydrogen(a)
    ]
    if not lig_atoms:
        return ()
    cutoff_sq = float(cutoff) ** 2
    protein = parse_structure_atoms(protein_text or "", protein_fmt)
    by_res: dict[ResidueKey, list] = defaultdict(list)
    for atom in protein:
        by_res[_atom_key3(atom)].append(atom)
    rows: list[str] = []
    for key in sorted(by_res):
        atoms = by_res[key]
        resn = (atoms[0].resn or "").upper()
        if resn not in _TITRATABLE and resn not in AMINO_ACIDS:
            continue
        if resn not in _TITRATABLE:
            continue
        heavies = [a for a in atoms if not _is_hydrogen(a)]
        if not heavies:
            continue
        if not any(_dist_sq(atom, lig) <= cutoff_sq for atom in heavies for lig in lig_atoms):
            continue
        rows.append(f"{key[0]}:{resn}{key[1]}{key[2]}")
        if len(rows) >= _MAX_QC_ROWS:
            break
    return tuple(rows)


def drop_long_missing_gaps(fixer, max_len: int) -> int:
    """Drop SEQRES gaps longer than *max_len* residues (terminal tags, disordered loops).

    PDBFixer places short missing stretches reasonably, but long N-terminal tags
    (for example 6BBU residues 839–866) and large disordered loops come out as
    strained models that do not help docking and can dominate minimization.
    """
    missing = getattr(fixer, "missingResidues", None)
    if not isinstance(missing, dict) or not missing:
        return 0
    try:
        limit = int(max_len)
    except (TypeError, ValueError):
        return 0
    if limit < 0:
        return 0
    dropped = 0
    for key in list(missing):
        gap = missing.get(key) or []
        if len(gap) > limit:
            dropped += len(gap)
            del missing[key]
    return dropped


def het_role(resn: str, kind: str = "") -> str:
    """Classify a residue as polymer, water, metal, cofactor, additive, or ligand."""
    from ..protein.structure_components import (
        AMINO_ACIDS,
        METAL_RESIDUES,
        NUCLEIC_ACIDS,
        WATER_RESIDUES,
    )
    from .protein_prepare_constants import COFACTOR_RESIDUES, CRYSTAL_ADDITIVE_RESIDUES

    name = (resn or "").strip().upper()
    kind_s = (kind or "").strip().lower()
    if kind_s == "water" or name in WATER_RESIDUES:
        return "water"
    if kind_s == "polymer" or name in AMINO_ACIDS or name in NUCLEIC_ACIDS:
        return "polymer"
    if kind_s == "metal" or name in METAL_RESIDUES:
        return "metal"
    if name in COFACTOR_RESIDUES:
        return "cofactor"
    if name in CRYSTAL_ADDITIVE_RESIDUES:
        return "additive"
    if kind_s:
        return kind_s
    return "ligand"


def drop_missing_residues_near_ligand(
    fixer,
    ligand_keys: set[ResidueKey],
    *,
    cutoff: float = _LOOP_LIGAND_CUTOFF,
) -> int:
    """Drop PDBFixer internal gaps whose flanking residues sit next to the ligand."""
    from openmm import unit

    missing = getattr(fixer, "missingResidues", None)
    if not isinstance(missing, dict) or not missing or not ligand_keys:
        return 0
    wanted = {_norm_key(*key) for key in ligand_keys}
    lig_xyz: list[tuple[float, float, float]] = []
    for atom in fixer.topology.atoms():
        residue = atom.residue
        chain = residue.chain.id if getattr(residue, "chain", None) is not None else ""
        key = _norm_key(
            chain,
            str(getattr(residue, "id", "") or ""),
            str(getattr(residue, "insertionCode", "") or ""),
        )
        if key not in wanted:
            continue
        pos = fixer.positions[atom.index].value_in_unit(unit.angstrom)
        lig_xyz.append((float(pos[0]), float(pos[1]), float(pos[2])))
    if not lig_xyz:
        return 0
    cutoff_sq = float(cutoff) ** 2
    chains = list(fixer.topology.chains())
    dropped = 0
    for gap_key in list(missing):
        chain_i, res_i = gap_key
        if chain_i >= len(chains):
            continue
        residues = list(chains[chain_i].residues())
        n_res = len(residues)
        if res_i == 0 or res_i >= n_res:
            continue
        flanks = [residues[res_i - 1], residues[res_i]] if res_i < n_res else [residues[res_i - 1]]
        if any(_topology_residue_near_ligand(fixer, res, lig_xyz, cutoff_sq) for res in flanks):
            del missing[gap_key]
            dropped += 1
    return dropped


_SEQRES_TEMPLATE_NAMES = {
    "MSE": "MET",
    "SEC": "CYS",
    "PYL": "LYS",
    "HID": "HIS",
    "HIE": "HIS",
    "HIP": "HIS",
    "HSD": "HIS",
    "HSE": "HIS",
    "HSP": "HIS",
    "CYX": "CYS",
    "CYM": "CYS",
    "ASH": "ASP",
    "GLH": "GLU",
    "LYN": "LYS",
}


def _template_resn(resn: str) -> str:
    from ..protein.structure_components import AMINO_ACIDS, NUCLEIC_ACIDS

    key = (resn or "").strip().upper()
    key = _SEQRES_TEMPLATE_NAMES.get(key, key)
    if key in AMINO_ACIDS or key in NUCLEIC_ACIDS:
        return key
    return ""


def apply_sequence_missing_residues(fixer, text: str, fmt: str) -> int:
    """Set ``fixer.missingResidues`` from SEQRES / mmCIF scheme vs topology.

    PDBFixer's own alignment requires ``len(SEQRES) >= (max_resid - min_resid + 1)``.
    Crystal numbering with large gaps (kinase inserts, tagged N-termini) fails that
    test and leaves ``missingResidues`` empty. Walk the construct sequence instead.
    """
    from ..protein.structure_components import AMINO_ACIDS, NUCLEIC_ACIDS, polymer_sequence_entries

    entries = polymer_sequence_entries(text or "", fmt)
    if not entries:
        return 0
    missing: dict[tuple[int, int], list[str]] = {}
    n_added = 0
    for chain in fixer.topology.chains():
        chain_id = getattr(chain, "id", "") or ""
        seq = entries.get(chain_id)
        if not seq:
            continue
        all_residues = list(chain.residues())

        def _is_polymer(res) -> bool:
            name = (getattr(res, "name", "") or "").strip().upper()
            return name in AMINO_ACIDS or name in NUCLEIC_ACIDS

        topo_keys = {
            _norm_key(
                chain_id,
                str(getattr(res, "id", "") or ""),
                str(getattr(res, "insertionCode", "") or ""),
            )[1:]
            for res in all_residues
            if _is_polymer(res)
        }
        cursor = 0
        gap: list[str] = []
        for resn, resi, icode, _present in seq:
            key = _norm_key(chain_id, resi, icode)[1:]
            if key in topo_keys:
                while cursor < len(all_residues) and not _is_polymer(all_residues[cursor]):
                    cursor += 1
                if gap:
                    missing[(chain.index, cursor)] = gap
                    n_added += len(gap)
                    gap = []
                cursor += 1
                continue
            template = _template_resn(resn)
            if template:
                gap.append(template)
        if gap:
            while cursor < len(all_residues) and not _is_polymer(all_residues[cursor]):
                cursor += 1
            missing[(chain.index, cursor)] = gap
            n_added += len(gap)
    if missing:
        fixer.missingResidues = missing
    return n_added


def _topology_residue_near_ligand(fixer, residue, lig_xyz, cutoff_sq: float) -> bool:
    from openmm import unit

    for atom in residue.atoms():
        pos = fixer.positions[atom.index].value_in_unit(unit.angstrom)
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        for lx, ly, lz in lig_xyz:
            dx, dy, dz = x - lx, y - ly, z - lz
            if dx * dx + dy * dy + dz * dz <= cutoff_sq:
                return True
    return False


def restrain_atom(
    atom, *, scheme: str, original_keys: set[ResidueKey], ligand_keys: set[ResidueKey]
) -> bool:
    """Whether *atom* should be harmonically restrained during Prepare minimization."""
    from ..protein.structure_components import AMINO_ACIDS, NUCLEIC_ACIDS

    scheme_l = (scheme or "backbone").lower()
    residue = atom.residue
    chain = residue.chain.id if getattr(residue, "chain", None) is not None else ""
    key = _norm_key(
        chain,
        str(getattr(residue, "id", "") or ""),
        str(getattr(residue, "insertionCode", "") or ""),
    )
    name = (atom.name or "").strip()
    resn = (getattr(residue, "name", "") or "").strip().upper()
    elem = ""
    element = getattr(atom, "element", None)
    if element is not None:
        elem = (getattr(element, "symbol", "") or "").upper()
    is_h = elem in {"H", "D"} or name.startswith("H")
    if scheme_l == "ca":
        return name == "CA" and (not original_keys or key in original_keys)
    polymer = resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS
    if polymer and name in {"N", "CA", "C", "O"} and (not original_keys or key in original_keys):
        return True
    if scheme_l == "backbone_ligand" and key in ligand_keys and not is_h:
        return True
    return False
