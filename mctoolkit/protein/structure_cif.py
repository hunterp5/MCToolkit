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


"""mmCIF tokenization, CCD chem-comp tables, and CIF rewrite helpers."""

from __future__ import annotations


from collections import defaultdict
from typing import Iterable

from .structure_component_types import (
    CifChemAtom,
    CifChemBond,
    StructureAtom,
    _atom_key4,
    _norm_chain,
    _residue_key3,
)

_CIF_LOOPS_CACHE_KEY: tuple | None = None
_CIF_LOOPS_CACHE: list[tuple[list[str], list[list[str]]]] | None = None
_HYDROGEN_ELEMS = frozenset({"H", "D", "T"})
_H_BOND_MAX_SQ = 1.45 * 1.45


def _cif_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text or "")
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] not in "\n\r":
                i += 1
            continue
        if ch == ";" and (i == 0 or text[i - 1] in "\n\r"):
            i += 1
            start = i
            while i < n:
                if text[i] == ";" and text[i - 1] in "\n\r":
                    tokens.append(text[start : i - 1])
                    i += 1
                    break
                i += 1
            else:
                tokens.append(text[start:])
            continue
        if ch in {"'", '"'}:
            quote = ch
            i += 1
            start = i
            while i < n:
                if text[i] == quote and (i + 1 >= n or text[i + 1].isspace()):
                    tokens.append(text[start:i])
                    i += 1
                    break
                i += 1
            else:
                tokens.append(text[start:])
            continue
        start = i
        while i < n and not text[i].isspace():
            i += 1
        tokens.append(text[start:i])
    return tokens


def _cif_missing(value: str) -> bool:
    return value in {".", "?", ""}


def _cif_yes(value: str) -> bool:
    return (value or "").strip().upper() in {"Y", "YES", "TRUE", "T", "1"}


def _parse_cif_loops(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return ``(tags, rows)`` for every ``loop_`` table in *text*."""
    global _CIF_LOOPS_CACHE_KEY, _CIF_LOOPS_CACHE
    key = (id(text), len(text), hash(text))
    cached = _CIF_LOOPS_CACHE
    if cached is not None and key == _CIF_LOOPS_CACHE_KEY:
        return cached
    loops = _parse_cif_loops_uncached(text)
    _CIF_LOOPS_CACHE_KEY = key
    _CIF_LOOPS_CACHE = loops
    return loops


def _parse_cif_loops_uncached(text: str) -> list[tuple[list[str], list[list[str]]]]:
    tokens = _cif_tokens(text)
    loops: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] != "loop_":
            i += 1
            continue
        i += 1
        tags: list[str] = []
        while i < n and tokens[i].startswith("_"):
            tags.append(tokens[i])
            i += 1
        ncols = len(tags)
        rows: list[list[str]] = []
        if ncols:
            while i + ncols <= n:
                nxt = tokens[i]
                if nxt == "loop_" or nxt.startswith("data_") or nxt.startswith("_"):
                    break
                rows.append(tokens[i : i + ncols])
                i += ncols
        loops.append((tags, rows))
    return loops


def _cif_loop_index(tags: list[str]) -> dict[str, int]:
    return {t.split(".", 1)[-1].lower(): idx for idx, t in enumerate(tags)}


def _cif_col(index: dict[str, int], *names: str) -> int | None:
    for name in names:
        if name.lower() in index:
            return index[name.lower()]
    return None


def _cif_cell(row: list[str], idx: int | None, default: str = "") -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return default
    value = row[idx]
    return default if _cif_missing(value) else value


def _cif_bond_order_int(value: str) -> int:
    """Map mmCIF ``value_order`` onto 1/2/3 for 3Dmol stick rendering."""
    key = (value or "").strip().lower()[:4]
    if key in {"doub", "delo"}:
        return 2
    if key in {"trip"}:
        return 3
    if key in {"quad"}:
        return 3
    if key in {"arom"}:
        return 2
    return 1


def _cif_bond_order_token(order: int) -> str:
    if int(order) >= 3:
        return "trip"
    if int(order) == 2:
        return "doub"
    return "sing"


def _chem_bond_pair(atom_id_1: str, atom_id_2: str) -> tuple[str, str]:
    return tuple(sorted(((atom_id_1 or "").strip(), (atom_id_2 or "").strip())))


def _is_h_elem(elem: str) -> bool:
    return (elem or "").upper() in _HYDROGEN_ELEMS


def _xyz_dist_sq(a: StructureAtom, b: StructureAtom) -> float:
    dx = float(a.x) - float(b.x)
    dy = float(a.y) - float(b.y)
    dz = float(a.z) - float(b.z)
    return dx * dx + dy * dy + dz * dz


def parse_cif_chem_comp_atoms(text: str) -> dict[str, tuple[CifChemAtom, ...]]:
    """Group ``_chem_comp_atom`` rows by ``comp_id``."""
    out: dict[str, list[CifChemAtom]] = defaultdict(list)
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_chem_comp_atom.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_comp = _cif_col(index, "comp_id")
        i_atom = _cif_col(index, "atom_id")
        i_sym = _cif_col(index, "type_symbol")
        i_leave = _cif_col(index, "pdbx_leaving_atom_flag")
        i_charge = _cif_col(index, "charge", "pdbx_formal_charge")
        i_arom = _cif_col(index, "pdbx_aromatic_flag")
        if i_comp is None or i_atom is None:
            continue
        for row in rows:
            comp = _cif_cell(row, i_comp).upper()
            atom_id = _cif_cell(row, i_atom)
            if not comp or not atom_id:
                continue
            symbol = _cif_cell(row, i_sym) or "C"
            charge_s = _cif_cell(row, i_charge, "0")
            try:
                charge = int(float(charge_s))
            except (TypeError, ValueError):
                charge = 0
            out[comp].append(
                CifChemAtom(
                    atom_id=atom_id,
                    symbol=symbol,
                    leaving=_cif_yes(_cif_cell(row, i_leave)),
                    charge=charge,
                    aromatic=_cif_yes(_cif_cell(row, i_arom)),
                )
            )
    return {key: tuple(vals) for key, vals in out.items()}


def parse_cif_chem_comp_bonds(text: str) -> dict[str, tuple[CifChemBond, ...]]:
    """Group ``_chem_comp_bond`` rows by ``comp_id``."""
    out: dict[str, list[CifChemBond]] = defaultdict(list)
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_chem_comp_bond.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_comp = _cif_col(index, "comp_id")
        i_a = _cif_col(index, "atom_id_1")
        i_b = _cif_col(index, "atom_id_2")
        i_ord = _cif_col(index, "value_order")
        i_arom = _cif_col(index, "pdbx_aromatic_flag")
        if i_comp is None or i_a is None or i_b is None:
            continue
        for row in rows:
            comp = _cif_cell(row, i_comp).upper()
            a1 = _cif_cell(row, i_a)
            a2 = _cif_cell(row, i_b)
            if not comp or not a1 or not a2:
                continue
            token = _cif_cell(row, i_ord, "sing")
            out[comp].append(
                CifChemBond(
                    atom_id_1=a1,
                    atom_id_2=a2,
                    order=_cif_bond_order_int(token),
                    order_token=token,
                    aromatic=_cif_yes(_cif_cell(row, i_arom)),
                )
            )
    return {key: tuple(vals) for key, vals in out.items()}


def cif_viewer_bond_tables(text: str) -> dict[str, list[list[object]]]:
    """Heavy-atom ``comp_id → [[atom1, atom2, order], …]`` for the protein canvas.

    3Dmol's text mmCIF parser never reads ``_chem_comp_bond``; the canvas
    replaces intra-residue *heavy* bonds after ``addModel`` so double/triple
    sticks draw. Hydrogen connectivity stays with distance inference because
    Amber/OpenMM often rename H while copied CCD tables keep old H ids.
    """
    h_ids_by_comp: dict[str, set[str]] = {}
    for comp, atoms in parse_cif_chem_comp_atoms(text).items():
        h_ids_by_comp[comp] = {atom.atom_id for atom in atoms if _is_h_elem(atom.symbol)}
    tables: dict[str, list[list[object]]] = {}
    for comp, bonds in parse_cif_chem_comp_bonds(text).items():
        h_ids = h_ids_by_comp.get(comp, set())
        tables[comp] = [
            [bond.atom_id_1, bond.atom_id_2, bond.order]
            for bond in bonds
            if bond.order >= 1 and bond.atom_id_1 not in h_ids and bond.atom_id_2 not in h_ids
        ]
    return tables


def rebuild_hydrogen_chem_bonds(
    atoms: Iterable[StructureAtom],
    chem_bonds: dict[str, tuple[CifChemBond, ...]],
) -> dict[str, tuple[CifChemBond, ...]]:
    """Replace H–X ``_chem_comp_bond`` rows using current coordinates.

    Amber/OpenMM often rename hydrogens while copied CCD tables keep the
    previous H ids, which draws stretched sticks if those bonds are applied.
    """
    if not chem_bonds:
        return chem_bonds
    h_names: dict[str, set[str]] = defaultdict(set)
    residues: dict[tuple[str, str, str, str], list[StructureAtom]] = defaultdict(list)
    for atom in atoms or ():
        resn = (atom.resn or "").upper()
        if not resn:
            continue
        residues[(atom.chain, atom.resi, atom.icode, resn)].append(atom)
        if _is_h_elem(atom.elem):
            h_names[resn].add(atom.name)
    observed: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for (_chain, _resi, _icode, resn), group in residues.items():
        if resn not in chem_bonds:
            continue
        heavies = [atom for atom in group if not _is_h_elem(atom.elem)]
        hydrogens = [atom for atom in group if _is_h_elem(atom.elem)]
        if not heavies:
            continue
        for hydrogen in hydrogens:
            parent = min(heavies, key=lambda heavy: _xyz_dist_sq(hydrogen, heavy))
            if _xyz_dist_sq(hydrogen, parent) > _H_BOND_MAX_SQ:
                continue
            observed[resn].add((hydrogen.name, parent.name))
    out: dict[str, tuple[CifChemBond, ...]] = {}
    for comp, bonds in chem_bonds.items():
        skip = h_names.get(comp, set())
        kept = [bond for bond in bonds if bond.atom_id_1 not in skip and bond.atom_id_2 not in skip]
        seen = {_chem_bond_pair(bond.atom_id_1, bond.atom_id_2) for bond in kept}
        for h_name, parent_name in sorted(
            observed.get(comp, ()), key=lambda pair: (pair[1], pair[0])
        ):
            pair = _chem_bond_pair(h_name, parent_name)
            if pair in seen:
                continue
            seen.add(pair)
            kept.append(
                CifChemBond(
                    atom_id_1=parent_name,
                    atom_id_2=h_name,
                    order=1,
                    order_token="sing",
                    aromatic=False,
                )
            )
        out[comp] = tuple(kept)
    return out


def rebuild_hydrogen_chem_tables(
    atoms: Iterable[StructureAtom],
    chem_atoms: dict[str, tuple[CifChemAtom, ...]],
    chem_bonds: dict[str, tuple[CifChemBond, ...]],
) -> tuple[dict[str, tuple[CifChemAtom, ...]], dict[str, tuple[CifChemBond, ...]]]:
    """Keep heavy CCD rows; rewrite hydrogen atoms/bonds from *atoms*."""
    bonds = rebuild_hydrogen_chem_bonds(atoms, chem_bonds)
    h_by_resn: dict[str, dict[str, str]] = defaultdict(dict)
    for atom in atoms or ():
        if not _is_h_elem(atom.elem):
            continue
        resn = (atom.resn or "").upper()
        if resn:
            h_by_resn[resn][atom.name] = (atom.elem or "H").upper()
    out_atoms: dict[str, tuple[CifChemAtom, ...]] = {}
    comps = sorted({*(chem_atoms or {}), *bonds, *h_by_resn})
    for comp in comps:
        kept = [row for row in (chem_atoms or {}).get(comp, ()) if not _is_h_elem(row.symbol)]
        for name, symbol in sorted(h_by_resn.get(comp, {}).items()):
            kept.append(CifChemAtom(atom_id=name, symbol=symbol))
        if kept:
            out_atoms[comp] = tuple(kept)
    return out_atoms, bonds


def repair_cif_hydrogen_chem_bonds(text: str) -> str:
    """Rewrite H–X ``_chem_comp_bond`` rows from the current ``_atom_site`` geometry."""
    if not parse_cif_chem_comp_bonds(text):
        return text
    from .structure_atoms import parse_structure_atoms

    site = parse_structure_atoms(text, "cif")
    chem_atoms, chem_bonds = rebuild_hydrogen_chem_tables(
        site,
        parse_cif_chem_comp_atoms(text),
        parse_cif_chem_comp_bonds(text),
    )
    return attach_cif_chem_comp(text, chem_atoms=chem_atoms, chem_bonds=chem_bonds)


def cif_has_component_bonds(text: str, resns: Iterable[str]) -> bool:
    """True when *text* has ``_chem_comp_bond`` rows for any of *resns*."""
    wanted = {str(resn).strip().upper() for resn in resns if str(resn).strip()}
    if not wanted:
        return False
    tables = parse_cif_chem_comp_bonds(text)
    return any(resn in tables and tables[resn] for resn in wanted)


def _cif_quote(value: str) -> str:
    """Quote an mmCIF token when it is empty or contains reserved characters."""
    s = "" if value is None else str(value)
    if s == "":
        return "."
    if (
        any(ch.isspace() for ch in s)
        or s[0] in {"_", "#", "$", "[", "]", "'", '"'}
        or s.startswith(("data_", "loop_", "save_", "stop_", "global_"))
    ):
        if "'" not in s:
            return f"'{s}'"
        return '"' + s.replace('"', "'") + '"'
    return s


def _cif_data_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (name or "").strip())
    return cleaned.strip("._-") or "prepared"


def format_chem_comp_cif_loops(
    atoms_by_comp: dict[str, tuple[CifChemAtom, ...]] | None,
    bonds_by_comp: dict[str, tuple[CifChemBond, ...]] | None,
) -> str:
    """mmCIF ``_chem_comp_atom`` / ``_chem_comp_bond`` loops for ligand connectivity."""
    chunks: list[str] = []
    atoms_by_comp = atoms_by_comp or {}
    bonds_by_comp = bonds_by_comp or {}
    comps = sorted({*atoms_by_comp, *bonds_by_comp})
    atom_rows: list[str] = []
    for comp in comps:
        for atom in atoms_by_comp.get(comp) or ():
            atom_rows.append(
                f"{_cif_quote(comp)} {_cif_quote(atom.atom_id)} {_cif_quote(atom.symbol)} "
                f"{atom.charge} {'Y' if atom.aromatic else 'N'}"
            )
    if atom_rows:
        chunks.append("loop_")
        chunks.append("_chem_comp_atom.comp_id")
        chunks.append("_chem_comp_atom.atom_id")
        chunks.append("_chem_comp_atom.type_symbol")
        chunks.append("_chem_comp_atom.charge")
        chunks.append("_chem_comp_atom.pdbx_aromatic_flag")
        chunks.extend(atom_rows)
        chunks.append("#")
    bond_rows: list[str] = []
    for comp in comps:
        for bond in bonds_by_comp.get(comp) or ():
            token = (bond.order_token or "sing").strip() or "sing"
            bond_rows.append(
                f"{_cif_quote(comp)} {_cif_quote(bond.atom_id_1)} {_cif_quote(bond.atom_id_2)} "
                f"{_cif_quote(token)} {'Y' if bond.aromatic else 'N'}"
            )
    if bond_rows:
        chunks.append("loop_")
        chunks.append("_chem_comp_bond.comp_id")
        chunks.append("_chem_comp_bond.atom_id_1")
        chunks.append("_chem_comp_bond.atom_id_2")
        chunks.append("_chem_comp_bond.value_order")
        chunks.append("_chem_comp_bond.pdbx_aromatic_flag")
        chunks.extend(bond_rows)
        chunks.append("#")
    return "\n".join(chunks) + ("\n" if chunks else "")


def atoms_to_mmcif(
    atoms: Iterable[StructureAtom],
    *,
    data_name: str = "prepared",
    remarks: list[str] | None = None,
    chem_atoms: dict[str, tuple[CifChemAtom, ...]] | None = None,
    chem_bonds: dict[str, tuple[CifChemBond, ...]] | None = None,
) -> str:
    """Write *atoms* as mmCIF ``_atom_site``, optionally with ligand bond tables."""
    rows: list[str] = []
    for serial, atom in enumerate(atoms, start=1):
        rec = "HETATM" if atom.het else "ATOM"
        # 3Dmol parseInt('.') is NaN; keep a numeric seq so ligand selections match.
        seq = atom.resi or "0"
        icode = atom.icode or "."
        alt = "."
        rows.append(
            f"{rec} {serial} {_cif_quote(atom.elem or 'X')} {_cif_quote(atom.name or atom.elem or 'X')} "
            f"{_cif_quote(alt)} {_cif_quote(atom.resn or 'UNK')} {_cif_quote(atom.chain)} "
            f"{_cif_quote(seq)} {_cif_quote(atom.resi or '0')} {_cif_quote(atom.resn or 'UNK')} "
            f"{_cif_quote(atom.chain)} {_cif_quote(icode)} "
            f"{atom.x:.3f} {atom.y:.3f} {atom.z:.3f} 1.00 0.00 1"
        )
    parts = [f"data_{_cif_data_name(data_name)}", "#"]
    for remark in remarks or []:
        text = str(remark).strip()
        if text:
            parts.append(f"# {text}")
    if remarks:
        parts.append("#")
    parts.extend(
        [
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.type_symbol",
            "_atom_site.label_atom_id",
            "_atom_site.label_alt_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_seq_id",
            "_atom_site.auth_comp_id",
            "_atom_site.auth_asym_id",
            "_atom_site.pdbx_PDB_ins_code",
            "_atom_site.Cartn_x",
            "_atom_site.Cartn_y",
            "_atom_site.Cartn_z",
            "_atom_site.occupancy",
            "_atom_site.B_iso_or_equiv",
            "_atom_site.pdbx_PDB_model_num",
        ]
    )
    parts.extend(rows)
    parts.append("#")
    chem = format_chem_comp_cif_loops(chem_atoms, chem_bonds)
    if chem:
        parts.append(chem.rstrip("\n"))
        parts.append("#")
    return "\n".join(parts) + "\n"


def pdb_to_mmcif(
    pdb_text: str,
    *,
    data_name: str = "prepared",
    remarks: list[str] | None = None,
    chem_atoms: dict[str, tuple[CifChemAtom, ...]] | None = None,
    chem_bonds: dict[str, tuple[CifChemBond, ...]] | None = None,
) -> str:
    """Convert PDB ATOM/HETATM records to mmCIF, optionally with ligand bond tables."""
    rows: list[str] = []
    serial = 0
    saw_model = False
    for line in (pdb_text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if rec == "ENDMDL" and rows:
            break
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        serial += 1
        name = padded[12:16].strip() or "X"
        alt = padded[16:17].strip() or "."
        resn = (padded[17:20].strip() or "UNK").upper()
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip() or "."
        try:
            x = float(padded[30:38])
            y = float(padded[38:46])
            z = float(padded[46:54])
        except ValueError:
            continue
        occ = padded[54:60].strip() or "1.00"
        bfac = padded[60:66].strip() or "0.00"
        elem = padded[76:78].strip() or "".join(ch for ch in name if ch.isalpha())[:2] or "X"
        seq = resi
        rows.append(
            f"{rec} {serial} {_cif_quote(elem.upper())} {_cif_quote(name)} {_cif_quote(alt)} "
            f"{_cif_quote(resn)} {_cif_quote(chain)} {_cif_quote(seq)} {_cif_quote(resi)} "
            f"{_cif_quote(resn)} {_cif_quote(chain)} {_cif_quote(icode)} "
            f"{x:.3f} {y:.3f} {z:.3f} {occ} {bfac} 1"
        )
    parts = [f"data_{_cif_data_name(data_name)}", "#"]
    for remark in remarks or []:
        text = str(remark).strip()
        if text:
            parts.append(f"# {text}")
    if remarks:
        parts.append("#")
    parts.extend(
        [
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.type_symbol",
            "_atom_site.label_atom_id",
            "_atom_site.label_alt_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
            "_atom_site.auth_seq_id",
            "_atom_site.auth_comp_id",
            "_atom_site.auth_asym_id",
            "_atom_site.pdbx_PDB_ins_code",
            "_atom_site.Cartn_x",
            "_atom_site.Cartn_y",
            "_atom_site.Cartn_z",
            "_atom_site.occupancy",
            "_atom_site.B_iso_or_equiv",
            "_atom_site.pdbx_PDB_model_num",
        ]
    )
    parts.extend(rows)
    parts.append("#")
    chem = format_chem_comp_cif_loops(chem_atoms, chem_bonds)
    if chem:
        parts.append(chem.rstrip("\n"))
        parts.append("#")
    return "\n".join(parts) + "\n"


def cif_comment_remarks(text: str) -> list[str]:
    """``#`` comment lines from an mmCIF, excluding OpenMM's generator stamp."""
    out: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#") or stripped == "#":
            continue
        note = stripped[1:].strip()
        if not note or note.lower().startswith("created with openmm"):
            continue
        out.append(note)
    return out


def delete_cif_residues(text: str, keys: set[tuple[str, str, str]]) -> str:
    """Drop mmCIF ``_atom_site`` rows whose ``(chain, resi, icode)`` is in *keys*."""
    if not keys:
        return text
    from .structure_atoms import parse_structure_atoms

    wanted = {_residue_key3(*key) for key in keys}
    atoms = [
        atom
        for atom in parse_structure_atoms(text, "cif")
        if _residue_key3(atom.chain, atom.resi, atom.icode) not in wanted
    ]
    remaining = {atom.resn.upper() for atom in atoms if atom.resn}
    chem_atoms = {
        comp: rows for comp, rows in parse_cif_chem_comp_atoms(text).items() if comp in remaining
    }
    chem_bonds = {
        comp: rows for comp, rows in parse_cif_chem_comp_bonds(text).items() if comp in remaining
    }
    return atoms_to_mmcif(
        atoms,
        remarks=cif_comment_remarks(text),
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
    )


def append_missing_cif_residues(dest: str, source: str, keys: set[tuple[str, str, str]]) -> str:
    """Copy mmCIF atoms from *source* when *dest* is missing those residues."""
    if not keys:
        return dest
    from .structure_atoms import parse_structure_atoms

    wanted = {_residue_key3(*key) for key in keys}
    dest_atoms = list(parse_structure_atoms(dest, "cif"))
    present = {_residue_key3(a.chain, a.resi, a.icode) for a in dest_atoms}
    extra = [
        atom
        for atom in parse_structure_atoms(source, "cif")
        if _residue_key3(atom.chain, atom.resi, atom.icode) in wanted
        and _residue_key3(atom.chain, atom.resi, atom.icode) not in present
    ]
    if not extra:
        return dest
    chem_atoms = parse_cif_chem_comp_atoms(dest)
    chem_bonds = parse_cif_chem_comp_bonds(dest)
    for comp, rows in parse_cif_chem_comp_atoms(source).items():
        chem_atoms.setdefault(comp, rows)
    for comp, rows in parse_cif_chem_comp_bonds(source).items():
        chem_bonds.setdefault(comp, rows)
    return atoms_to_mmcif(
        dest_atoms + extra,
        remarks=cif_comment_remarks(dest) or cif_comment_remarks(source),
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
    )


def delete_cif_atoms(text: str, keys: set[tuple[str, str, str, str]]) -> str:
    """Drop mmCIF ``_atom_site`` rows by ``(chain, resi, icode, name)``."""
    wanted = {_atom_key4(*key) for key in keys}
    if not wanted:
        return text
    from .structure_atoms import parse_structure_atoms

    atoms = [
        atom
        for atom in parse_structure_atoms(text, "cif")
        if _atom_key4(atom.chain, atom.resi, atom.icode, atom.name) not in wanted
    ]
    remaining_names: dict[str, set[str]] = defaultdict(set)
    remaining_resn: set[str] = set()
    for atom in atoms:
        resn = (atom.resn or "").upper()
        if not resn:
            continue
        remaining_resn.add(resn)
        remaining_names[resn].add(atom.name)
    chem_atoms = {
        comp: tuple(row for row in rows if row.atom_id in remaining_names.get(comp, set()))
        for comp, rows in parse_cif_chem_comp_atoms(text).items()
        if comp in remaining_resn
    }
    chem_atoms = {comp: rows for comp, rows in chem_atoms.items() if rows}
    chem_bonds = {
        comp: tuple(
            bond
            for bond in rows
            if bond.atom_id_1 in remaining_names.get(comp, set())
            and bond.atom_id_2 in remaining_names.get(comp, set())
        )
        for comp, rows in parse_cif_chem_comp_bonds(text).items()
        if comp in remaining_resn
    }
    chem_bonds = {comp: rows for comp, rows in chem_bonds.items() if rows}
    return atoms_to_mmcif(
        atoms,
        remarks=cif_comment_remarks(text),
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
    )


def add_cif_chem_bond(
    text: str,
    comp_id: str,
    atom_id_1: str,
    atom_id_2: str,
    *,
    order: int = 1,
) -> str:
    """Add or replace an intra-residue ``_chem_comp_bond`` row."""
    comp = (comp_id or "").strip().upper()
    a1 = (atom_id_1 or "").strip()
    a2 = (atom_id_2 or "").strip()
    if not comp or not a1 or not a2 or a1 == a2:
        return text
    pair = _chem_bond_pair(a1, a2)
    token = _cif_bond_order_token(order)
    bonds = dict(parse_cif_chem_comp_bonds(text))
    current = [
        bond
        for bond in (bonds.get(comp) or ())
        if _chem_bond_pair(bond.atom_id_1, bond.atom_id_2) != pair
    ]
    current.append(
        CifChemBond(
            atom_id_1=a1,
            atom_id_2=a2,
            order=int(order) if int(order) >= 1 else 1,
            order_token=token,
        )
    )
    bonds[comp] = tuple(current)
    return attach_cif_chem_comp(text, chem_atoms=parse_cif_chem_comp_atoms(text), chem_bonds=bonds)


def remove_cif_chem_bond(text: str, comp_id: str, atom_id_1: str, atom_id_2: str) -> str:
    """Drop an intra-residue ``_chem_comp_bond`` row if present."""
    comp = (comp_id or "").strip().upper()
    pair = _chem_bond_pair(atom_id_1, atom_id_2)
    if not comp or not pair[0] or pair[0] == pair[1]:
        return text
    bonds = dict(parse_cif_chem_comp_bonds(text))
    current = tuple(
        bond
        for bond in (bonds.get(comp) or ())
        if _chem_bond_pair(bond.atom_id_1, bond.atom_id_2) != pair
    )
    if current:
        bonds[comp] = current
    else:
        bonds.pop(comp, None)
    return attach_cif_chem_comp(text, chem_atoms=parse_cif_chem_comp_atoms(text), chem_bonds=bonds)


def attach_cif_chem_comp(
    text: str,
    chem_atoms: dict[str, tuple[CifChemAtom, ...]] | None = None,
    chem_bonds: dict[str, tuple[CifChemBond, ...]] | None = None,
) -> str:
    """Replace or append ``_chem_comp_atom`` / ``_chem_comp_bond`` loops on *text*."""
    from .structure_atoms import parse_structure_atoms

    atoms = parse_structure_atoms(text, "cif")
    have_atoms = chem_atoms if chem_atoms is not None else parse_cif_chem_comp_atoms(text)
    have_bonds = chem_bonds if chem_bonds is not None else parse_cif_chem_comp_bonds(text)
    return atoms_to_mmcif(
        atoms,
        remarks=cif_comment_remarks(text),
        chem_atoms=have_atoms,
        chem_bonds=have_bonds,
    )
