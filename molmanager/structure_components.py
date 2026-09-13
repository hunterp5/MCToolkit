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

"""Inventory polymer chains, ligands, metals, and solvent from crystallographic files."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

AMINO_ACIDS = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
        "SEC",
        "PYL",
        "ASX",
        "GLX",
        "UNK",
        "MSE",
        "HYP",
        "MLY",
        "M3L",
        "PTR",
        "SEP",
        "TPO",
        "CSO",
        "CSD",
        "HID",
        "HIE",
        "HIP",
        "CYX",
        "ASH",
        "GLH",
        "LYN",
    }
)
AA_THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "U",
    "PYL": "O",
    "ASX": "B",
    "GLX": "Z",
    "UNK": "X",
    "MSE": "M",
    "HYP": "P",
    "MLY": "K",
    "M3L": "K",
    "PTR": "Y",
    "SEP": "S",
    "TPO": "T",
    "CSO": "C",
    "CSD": "C",
    "HID": "H",
    "HIE": "H",
    "HIP": "H",
    "CYX": "C",
    "ASH": "D",
    "GLH": "E",
    "LYN": "K",
}
AA_ONE_TO_THREE = {
    "A": "ALA",
    "R": "ARG",
    "N": "ASN",
    "D": "ASP",
    "C": "CYS",
    "Q": "GLN",
    "E": "GLU",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "L": "LEU",
    "K": "LYS",
    "M": "MET",
    "F": "PHE",
    "P": "PRO",
    "S": "SER",
    "T": "THR",
    "W": "TRP",
    "Y": "TYR",
    "V": "VAL",
    "U": "SEC",
    "O": "PYL",
    "B": "ASX",
    "Z": "GLX",
    "X": "UNK",
}
VALID_SEQUENCE_LETTERS = frozenset(AA_ONE_TO_THREE)
# Hetero tokens in the Sequence window (one character per residue).
SEQ_LETTER_LIGAND = "+"
SEQ_LETTER_METAL = "*"
SEQ_LETTER_WATER = "~"
SEQ_LETTER_OTHER = "?"
HETERO_SEQUENCE_LETTERS = frozenset(
    {SEQ_LETTER_LIGAND, SEQ_LETTER_METAL, SEQ_LETTER_WATER, SEQ_LETTER_OTHER}
)
SEQUENCE_ALPHABET = (
    VALID_SEQUENCE_LETTERS
    | {letter.lower() for letter in VALID_SEQUENCE_LETTERS}
    | HETERO_SEQUENCE_LETTERS
)
_REMARK_465_ROW = re.compile(
    r"^REMARK\s+465\s+(?:\d+\s+)?([A-Z0-9]{1,3})\s+([A-Za-z0-9])\s+(-?\d+)([A-Za-z])?\s*$",
    re.IGNORECASE,
)
NUCLEIC_THREE_TO_ONE = {
    "A": "A",
    "C": "C",
    "G": "G",
    "T": "T",
    "U": "U",
    "I": "I",
    "DA": "A",
    "DC": "C",
    "DG": "G",
    "DT": "T",
    "DU": "U",
    "DI": "I",
    "ADE": "A",
    "CYT": "C",
    "GUA": "G",
    "THY": "T",
    "URA": "U",
    "5MC": "C",
    "5MU": "U",
    "PSU": "U",
    "H2U": "U",
    "M2G": "G",
    "OMC": "C",
    "OMG": "G",
}
NUCLEIC_ACIDS = frozenset(
    {
        "A",
        "C",
        "G",
        "T",
        "U",
        "I",
        "DA",
        "DC",
        "DG",
        "DT",
        "DU",
        "DI",
        "ADE",
        "CYT",
        "GUA",
        "THY",
        "URA",
        "5MC",
        "5MU",
        "PSU",
        "H2U",
        "M2G",
        "OMC",
        "OMG",
    }
)
WATER_RESIDUES = frozenset({"HOH", "WAT", "H2O", "DOD", "D2O", "TIP", "SOL", "OH2"})
POCKET_CUTOFF_ANGSTROM = 4.5
POLAR_HEAVY_ELEMENTS = frozenset({"N", "O", "S", "F"})
_HYDROGEN_ELEMENTS = frozenset({"H", "D"})
_POLAR_H_BOND_ANGSTROM = 1.35
METAL_RESIDUES = frozenset(
    {
        "LI",
        "NA",
        "K",
        "RB",
        "CS",
        "MG",
        "CA",
        "SR",
        "BA",
        "MN",
        "FE",
        "FE2",
        "FE3",
        "CO",
        "NI",
        "CU",
        "ZN",
        "CD",
        "HG",
        "AU",
        "AG",
        "PT",
        "PD",
        "IR",
        "OS",
        "RU",
        "RH",
        "AL",
        "GA",
        "IN",
        "TL",
        "PB",
        "V",
        "CR",
        "MO",
        "W",
        "CL",
        "BR",
        "F",
        "I",
        "IOD",
        "YB",
        "GD",
        "LA",
        "CE",
        "SM",
        "EU",
        "TB",
        "HO",
        "ER",
        "LU",
        "Y",
        "SC",
        "TI",
        "ZR",
        "HF",
        "RE",
        "W",
        "U",
        "TH",
        "AM",
        "CM",
    }
)
METAL_ELEMENTS = frozenset(
    {
        "LI",
        "NA",
        "K",
        "RB",
        "CS",
        "MG",
        "CA",
        "SR",
        "BA",
        "MN",
        "FE",
        "CO",
        "NI",
        "CU",
        "ZN",
        "CD",
        "HG",
        "AU",
        "AG",
        "PT",
        "PD",
        "IR",
        "OS",
        "RU",
        "RH",
        "AL",
        "GA",
        "IN",
        "TL",
        "PB",
        "V",
        "CR",
        "MO",
        "W",
        "Y",
        "SC",
        "TI",
        "ZR",
        "HF",
        "RE",
        "U",
        "GD",
        "LA",
        "CE",
        "SM",
        "EU",
        "TB",
        "HO",
        "ER",
        "LU",
        "YB",
    }
)
CHAIN_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#bcbd22",
    "#7f7f7f",
    "#393b79",
    "#637939",
    "#8c6d31",
    "#843c39",
    "#7b4173",
    "#3182bd",
    "#e6550d",
    "#31a354",
    "#756bb1",
    "#636363",
)

STRUCTURE_FORMAT_BY_SUFFIX = {
    ".pdb": "pdb",
    ".ent": "pdb",
    ".brk": "pdb",
    ".pdbqt": "pdbqt",
    ".cif": "cif",
    ".mmcif": "cif",
    ".mcif": "cif",
    ".pqr": "pqr",
    ".gro": "gro",
    ".mol2": "mol2",
    ".sdf": "sdf",
    ".mol": "sdf",
    ".xyz": "xyz",
}


@dataclass(frozen=True)
class StructureComponent:
    """One Manager row: a polymer chain, ligand, metal, or solvent group."""

    component_id: str
    kind: str
    label: str
    chain: str
    resn: str
    resi: str
    icode: str
    n_atoms: int
    n_residues: int
    color: str
    default_style: str
    default_visible: bool
    selection: dict[str, Any] = field(default_factory=dict)
    structure_id: str = ""

    def to_payload(self) -> dict[str, Any]:
        """JSON-serializable dict consumed by the 3Dmol page."""
        return {
            "id": self.component_id,
            "kind": self.kind,
            "label": self.label,
            "chain": self.chain,
            "resn": self.resn,
            "resi": self.resi,
            "icode": self.icode,
            "nAtoms": self.n_atoms,
            "nResidues": self.n_residues,
            "color": self.color,
            "style": self.default_style,
            "visible": self.default_visible,
            "selection": self.selection,
            "structureId": self.structure_id,
        }


@dataclass(frozen=True)
class LoadedStructure:
    """File contents plus Manager inventory for the protein viewer."""

    path: Path
    text: str
    sniffed_format: str
    viewer_format: str
    components: tuple[StructureComponent, ...]


@dataclass(frozen=True)
class PolymerResidue:
    """One residue in a sequence tab, keyed by chain + residue number."""

    chain: str
    resn: str
    resi: str
    icode: str
    letter: str
    kind: str = "polymer"
    structure_id: str = ""
    model: int | None = None

    def selection(self) -> dict[str, Any]:
        """3Dmol selection that stays valid after residue-name mutations."""
        sel: dict[str, Any] = {"chain": self.chain, "resi": _resi_selection_value(self.resi)}
        if self.icode:
            sel["icode"] = self.icode
        if self.model is not None:
            sel["model"] = int(self.model)
        return sel


@dataclass
class PolymerChain:
    """Ordered residue sequence for one chain ID (polymer plus heteros)."""

    chain: str
    residues: list[PolymerResidue]
    structure_id: str = ""
    structure_name: str = ""

    @property
    def sequence(self) -> str:
        return "".join(res.letter for res in self.residues)


@dataclass(frozen=True)
class SequenceEdit:
    """Result of comparing an edited 1-letter string to the current chain sequence."""

    mutations: tuple[tuple[int, str], ...]
    deletions: tuple[int, ...]
    rejected_insert: bool
    invalid_letter: bool


@dataclass(frozen=True)
class StructureAtom:
    """One coordinate record used for pocket contact and polar-H overlay."""

    chain: str
    resn: str
    resi: str
    icode: str
    name: str
    elem: str
    x: float
    y: float
    z: float
    het: bool
    altloc: str = ""
    occupancy: float = 1.0
    bfactor: float = 0.0


@dataclass(frozen=True)
class PocketViewPlan:
    """Ligand zoom targets, nearby polymer residues, and polar-hydrogen overlay PDB."""

    ligand_sels: tuple[dict[str, Any], ...]
    residue_sels: tuple[dict[str, Any], ...]
    polar_h_pdb: str


@dataclass
class _ResidueBucket:
    chain: str
    resn: str
    resi: str
    icode: str
    het: bool
    n_atoms: int = 0
    elements: set[str] = field(default_factory=set)


def sniff_structure_format(path: str | Path, text: str) -> str:
    """Return a 3Dmol-oriented format id from suffix and contents."""
    suffix = Path(path).suffix.lower()
    if suffix in STRUCTURE_FORMAT_BY_SUFFIX:
        return STRUCTURE_FORMAT_BY_SUFFIX[suffix]
    stripped = (text or "").lstrip()
    if stripped.startswith("data_"):
        return "cif"
    head = stripped[:80].upper()
    if head.startswith(
        ("ATOM", "HETATM", "HEADER", "TITLE", "REMARK", "MODEL", "CRYST1", "COMPND")
    ):
        return "pdb"
    if "ROOT" in stripped[:400] or "TORSDOF" in stripped[:800]:
        return "pdbqt"
    return "pdb"


def viewer_format_for(sniffed: str) -> str:
    """3Dmol ``addModel`` format string for a sniffed file type."""
    if sniffed in {"pdbqt", "pdb", "pqr", "ent"}:
        return "pdb" if sniffed != "pqr" else "pqr"
    if sniffed in {"cif", "mmcif"}:
        return "cif"
    return sniffed


def parse_structure_components(text: str, fmt: str) -> tuple[StructureComponent, ...]:
    """Build Manager rows from PDB-like or mmCIF atom records."""
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        residues = _residues_from_cif(text)
    else:
        residues = _residues_from_pdb(text)
    return _components_from_residues(residues)


def scope_structure_component(
    spec: StructureComponent, *, structure_id: str, model: int
) -> StructureComponent:
    """Prefix *spec* so it is unique in a multi-file viewer session."""
    sel = dict(spec.selection or {})
    sel["model"] = int(model)
    cid = spec.component_id
    prefix = f"{structure_id}:"
    if not cid.startswith(prefix):
        cid = prefix + cid
    return replace(spec, component_id=cid, structure_id=structure_id, selection=sel)


def load_structure_file(path: str | Path) -> LoadedStructure:
    """Read a crystallographic file and inventory its chains / heteros."""
    rec = Path(str(path)).expanduser()
    raw_bytes = rec.read_bytes()
    if b"\x00" in raw_bytes[:4096]:
        raise ValueError(f"{rec.name} looks binary; use PDB, mmCIF, PDBQT, or another text format.")
    text = raw_bytes.decode("utf-8", errors="replace")
    sniffed = sniff_structure_format(rec, text)
    parse_fmt = "cif" if sniffed == "cif" else "pdb"
    components = parse_structure_components(text, parse_fmt)
    return LoadedStructure(
        path=rec,
        text=text,
        sniffed_format=sniffed,
        viewer_format=viewer_format_for(sniffed),
        components=components,
    )


def component_id_for_atom(
    components: Iterable[StructureComponent],
    *,
    chain: str,
    resn: str,
    resi: str | int | None,
    icode: str = "",
    model: int | None = None,
    structure_id: str = "",
) -> str | None:
    """Map a clicked 3Dmol atom onto the most specific Manager row."""
    chain_s = _norm_chain(chain)
    resn_s = (resn or "").strip().upper()
    resi_s = str(resi).strip() if resi is not None else ""
    icode_s = (icode or "").strip()
    items = list(components)
    if model is not None:
        scoped = [
            c
            for c in items
            if (c.selection or {}).get("model") == model
            or (c.selection or {}).get("model") == int(model)
        ]
        if scoped:
            items = scoped
    if structure_id:
        scoped = [c for c in items if c.structure_id == structure_id]
        if scoped:
            items = scoped
    for kind in ("water", "ligand", "metal", "other"):
        for comp in items:
            if comp.kind != kind:
                continue
            if kind == "water":
                if resn_s not in WATER_RESIDUES:
                    continue
                if comp.chain and _norm_chain(comp.chain) != chain_s:
                    continue
                return comp.component_id
            if _norm_chain(comp.chain) != chain_s:
                continue
            if comp.resn.upper() != resn_s:
                continue
            if comp.resi and comp.resi != resi_s:
                continue
            if comp.icode and comp.icode != icode_s:
                continue
            return comp.component_id
    for comp in items:
        if comp.kind == "polymer" and _norm_chain(comp.chain) == chain_s:
            return comp.component_id
    if items:
        return items[0].component_id
    return None


def _optional_float(text: str, default: float) -> float:
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return default


def _norm_chain(chain: str | None) -> str:
    raw = (chain or "").strip()
    return raw if raw else "?"


def _residues_from_pdb(text: str) -> list[_ResidueBucket]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    saw_model = False
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if rec == "ENDMDL" and buckets:
            break
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        name = padded[12:16].strip()
        resn = padded[17:20].strip() or name[:3]
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip()
        elem = padded[76:78].strip() or "".join(ch for ch in name if ch.isalpha())[:2]
        het = rec == "HETATM"
        key = (chain, resn.upper(), resi, icode)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _ResidueBucket(chain=chain, resn=resn.upper(), resi=resi, icode=icode, het=het)
            buckets[key] = bucket
        bucket.n_atoms += 1
        bucket.elements.add(elem.upper())
        bucket.het = bucket.het or het
    return list(buckets.values())


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


@dataclass(frozen=True)
class CifChemAtom:
    """One ``_chem_comp_atom`` row."""

    atom_id: str
    symbol: str
    leaving: bool = False
    charge: int = 0
    aromatic: bool = False


@dataclass(frozen=True)
class CifChemBond:
    """One ``_chem_comp_bond`` row (intra-residue CCD connectivity)."""

    atom_id_1: str
    atom_id_2: str
    order: int
    order_token: str
    aromatic: bool = False


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
    """``comp_id → [[atom1, atom2, order], …]`` for bonds with order > 1.

    3Dmol's text mmCIF parser never reads ``_chem_comp_bond``; the protein
    canvas applies this table after ``addModel`` so double/triple sticks draw.
    """
    tables: dict[str, list[list[object]]] = {}
    for comp, bonds in parse_cif_chem_comp_bonds(text).items():
        rows = [[bond.atom_id_1, bond.atom_id_2, bond.order] for bond in bonds if bond.order >= 1]
        if rows:
            tables[comp] = rows
    return tables


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


def _residues_from_cif(text: str) -> list[_ResidueBucket]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_atom_site.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_group = _cif_col(index, "group_PDB")
        i_symbol = _cif_col(index, "type_symbol")
        i_comp = _cif_col(index, "auth_comp_id", "label_comp_id")
        i_asym = _cif_col(index, "auth_asym_id", "label_asym_id")
        i_seq = _cif_col(index, "auth_seq_id", "label_seq_id")
        i_icode = _cif_col(index, "pdbx_PDB_ins_code")
        i_model = _cif_col(index, "pdbx_PDB_model_num")
        first_model = ""
        for row in rows:
            if i_model is not None:
                model = _cif_cell(row, i_model, "1") or "1"
                if not first_model:
                    first_model = model
                elif model != first_model:
                    continue
            group = _cif_cell(row, i_group, "ATOM")
            resn = _cif_cell(row, i_comp, "UNK").upper() or "UNK"
            chain_raw = _cif_cell(row, i_asym, "?") or "?"
            resi = _cif_cell(row, i_seq, "0") or "0"
            icode = _cif_cell(row, i_icode)
            elem = _cif_cell(row, i_symbol)
            chain = _norm_chain(chain_raw)
            het = str(group).upper().startswith("HET")
            key = (chain, resn, str(resi), icode)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = _ResidueBucket(
                    chain=chain, resn=resn, resi=str(resi), icode=icode, het=het
                )
                buckets[key] = bucket
            bucket.n_atoms += 1
            bucket.elements.add(elem.upper())
            bucket.het = bucket.het or het
    return list(buckets.values())


def _classify_residue(bucket: _ResidueBucket) -> str:
    resn = bucket.resn.upper()
    if resn in WATER_RESIDUES:
        return "water"
    if resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS:
        return "polymer"
    if resn in METAL_RESIDUES:
        return "metal"
    elems = {el.upper() for el in bucket.elements if el}
    if bucket.n_atoms <= 2 and elems and elems <= METAL_ELEMENTS:
        return "metal"
    if bucket.n_atoms == 1 and elems <= ({"CL", "BR", "F", "I"} | METAL_ELEMENTS):
        return "metal"
    if bucket.het:
        return "ligand"
    return "polymer"


def _resi_selection_value(resi: str) -> int | str:
    try:
        return int(resi)
    except (TypeError, ValueError):
        return resi


def _residue_selection(bucket: _ResidueBucket) -> dict[str, Any]:
    sel: dict[str, Any] = {
        "chain": bucket.chain,
        "resn": bucket.resn,
        "resi": _resi_selection_value(bucket.resi),
    }
    if bucket.icode:
        sel["icode"] = bucket.icode
    if bucket.het:
        sel["hetflag"] = True
    return sel


def _not_or(parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not parts:
        return None
    if len(parts) == 1:
        return {"not": parts[0]}
    return {"not": {"or": parts}}


def _and(parts: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned = [p for p in parts if p]
    if not cleaned:
        return {}
    if len(cleaned) == 1:
        return cleaned[0]
    return {"and": cleaned}


def _whole_structure_component(*, n_atoms: int = 0, n_residues: int = 0) -> StructureComponent:
    return StructureComponent(
        component_id="structure",
        kind="other",
        label="Structure",
        chain="",
        resn="",
        resi="",
        icode="",
        n_atoms=n_atoms,
        n_residues=n_residues,
        color="#7f8c8d",
        default_style="stick",
        default_visible=True,
        selection={},
    )


def _components_from_residues(residues: list[_ResidueBucket]) -> tuple[StructureComponent, ...]:
    if not residues:
        return (_whole_structure_component(),)
    classified = [(bucket, _classify_residue(bucket)) for bucket in residues]
    by_kind: dict[str, list[_ResidueBucket]] = defaultdict(list)
    for bucket, kind in classified:
        by_kind[kind].append(bucket)

    chain_ids = sorted({bucket.chain for bucket, _kind in classified}, key=_chain_sort_key)
    chain_color = {chain: CHAIN_COLORS[i % len(CHAIN_COLORS)] for i, chain in enumerate(chain_ids)}
    water_resns = sorted({b.resn for b in by_kind.get("water", [])})

    out: list[StructureComponent] = []
    ligand_color_i = 0
    for chain in chain_ids:
        polymer_res = [b for b in by_kind.get("polymer", []) if b.chain == chain]
        if polymer_res:
            exclude: list[dict[str, Any]] = [{"resn": resn} for resn in water_resns]
            for kind in ("ligand", "metal", "other"):
                for bucket in by_kind.get(kind, []):
                    if bucket.chain != chain:
                        continue
                    exclude.append(_residue_selection(bucket))
            sel = _and([{"chain": chain}, _not_or(exclude) or {}])
            out.append(
                StructureComponent(
                    component_id=f"polymer:{chain}",
                    kind="polymer",
                    label="Polymer",
                    chain=chain,
                    resn="",
                    resi="",
                    icode="",
                    n_atoms=sum(b.n_atoms for b in polymer_res),
                    n_residues=len(polymer_res),
                    color=chain_color[chain],
                    default_style="cartoon",
                    default_visible=True,
                    selection=sel,
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("ligand", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            color = CHAIN_COLORS[(ligand_color_i + 4) % len(CHAIN_COLORS)]
            ligand_color_i += 1
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"ligand:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="ligand",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color=color,
                    default_style="ballstick",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("metal", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"metal:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="metal",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color="#f1c40f",
                    default_style="sphere",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

        waters = [b for b in by_kind.get("water", []) if b.chain == chain]
        if waters:
            chain_water_resns = sorted({b.resn for b in waters})
            if len(chain_water_resns) == 1:
                resn_sel: dict[str, Any] = {"resn": chain_water_resns[0]}
            else:
                resn_sel = {"or": [{"resn": r} for r in chain_water_resns]}
            out.append(
                StructureComponent(
                    component_id=f"water:{chain}",
                    kind="water",
                    label="Water",
                    chain=chain,
                    resn=chain_water_resns[0] if len(chain_water_resns) == 1 else "",
                    resi="",
                    icode="",
                    n_atoms=sum(b.n_atoms for b in waters),
                    n_residues=len(waters),
                    color="#e74c3c",
                    default_style="sphere",
                    default_visible=False,
                    selection=_and([{"chain": chain}, resn_sel]),
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("other", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"other:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="other",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color="#7f8c8d",
                    default_style="stick",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

    if not out:
        n_atoms = sum(b.n_atoms for b in residues)
        out.append(_whole_structure_component(n_atoms=n_atoms, n_residues=len(residues)))
    return tuple(out)


def _chain_sort_key(chain: str) -> tuple[int, str]:
    return (0 if len(chain) == 1 and chain.isalpha() else 1, chain)


def _resi_sort(resi: str) -> tuple[int, str]:
    try:
        return (int(resi), resi)
    except (TypeError, ValueError):
        return (10**9, resi)


def amino_acid_letter(resn: str) -> str:
    """One-letter code for a residue name; unknown amino acids become X."""
    return AA_THREE_TO_ONE.get((resn or "").strip().upper(), "X")


def sequence_letter_for(resn: str, kind: str) -> str:
    """Sequence-window character for a residue of the given Manager kind."""
    if kind == "water":
        return SEQ_LETTER_WATER
    if kind == "metal":
        return SEQ_LETTER_METAL
    if kind == "ligand":
        return SEQ_LETTER_LIGAND
    if kind == "other":
        return SEQ_LETTER_OTHER
    key = (resn or "").strip().upper()
    if key in NUCLEIC_THREE_TO_ONE:
        letter = NUCLEIC_THREE_TO_ONE[key]
    elif key in AA_THREE_TO_ONE:
        letter = AA_THREE_TO_ONE[key]
    elif kind in {"polymer", "missing"}:
        letter = amino_acid_letter(key)
    else:
        return SEQ_LETTER_OTHER
    return letter.lower() if kind == "missing" else letter


def letter_to_resn(letter: str) -> str | None:
    """Canonical PDB residue name for a 1-letter code, or None if invalid."""
    key = (letter or "").strip().upper()
    return AA_ONE_TO_THREE.get(key)


def _norm_seq_resi(resi: str) -> str:
    raw = str(resi or "").strip() or "0"
    try:
        return str(int(raw))
    except ValueError:
        return raw


def polymer_sequence_entries(
    text: str, fmt: str
) -> dict[str, tuple[tuple[str, str, str, bool], ...]]:
    """SEQRES / mmCIF polymer residues: ``chain → ((resn, resi, icode, present), ...)``.

    ``present`` is False when coordinates are missing (REMARK 465 or ``pdb_mon_id`` ``?``).
    """
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        entries = _polymer_seq_from_cif(text)
    else:
        entries = _polymer_seq_from_pdb(text)
    return {chain: tuple(rows) for chain, rows in entries.items() if rows}


def _polymer_seq_from_cif(text: str) -> dict[str, list[tuple[str, str, str, bool]]]:
    out: dict[str, list[tuple[str, str, str, bool]]] = defaultdict(list)
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_pdbx_poly_seq_scheme.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_strand = _cif_col(index, "pdb_strand_id", "asym_id")
        i_resn = _cif_col(index, "mon_id", "auth_mon_id", "pdb_mon_id")
        i_seq = _cif_col(index, "auth_seq_num", "pdb_seq_num", "ndb_seq_num")
        i_auth_seq = _cif_col(index, "auth_seq_num")
        i_pdb_seq = _cif_col(index, "pdb_seq_num")
        i_observed = _cif_col(index, "pdb_mon_id", "auth_mon_id")
        i_icode = _cif_col(index, "pdb_ins_code")
        i_het = _cif_col(index, "hetero")
        if i_strand is None or i_resn is None:
            continue
        for row in rows:
            if _cif_yes(_cif_cell(row, i_het)):
                continue
            resn = _cif_cell(row, i_resn).upper()
            if not resn:
                continue
            chain = _norm_chain(_cif_cell(row, i_strand, "?") or "?")
            observed_name = _cif_cell(row, i_observed) if i_observed is not None else resn
            present = not _cif_missing(observed_name)
            seq_raw = ""
            if present and i_auth_seq is not None:
                seq_raw = _cif_cell(row, i_auth_seq)
            if _cif_missing(seq_raw) and i_pdb_seq is not None:
                seq_raw = _cif_cell(row, i_pdb_seq)
            if _cif_missing(seq_raw) and i_seq is not None:
                seq_raw = _cif_cell(row, i_seq)
            resi = _norm_seq_resi(seq_raw)
            icode = _cif_cell(row, i_icode)
            if _cif_missing(icode):
                icode = ""
            out[chain].append((resn, resi, icode, present))
    return dict(out)


def _pdb_seqres_names(text: str) -> dict[str, list[str]]:
    names: dict[str, list[str]] = defaultdict(list)
    for line in (text or "").splitlines():
        if not line.upper().startswith("SEQRES"):
            continue
        padded = line.ljust(80)
        chain = _norm_chain(padded[11:12])
        names[chain].extend(tok.upper() for tok in padded[19:].split() if tok)
    return dict(names)


def _pdb_remark_465(text: str) -> dict[str, list[tuple[str, str, str]]]:
    missing: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for line in (text or "").splitlines():
        if not line.upper().startswith("REMARK 465"):
            continue
        padded = line.ljust(80)
        header = padded[10:].strip().upper()
        if not header or header.startswith(
            ("MISSING", "THE FOLLOWING", "EXPERIMENT", "M RES", "IDENT", "SSSEQ")
        ):
            continue
        resn = padded[15:18].strip().upper()
        chain = _norm_chain(padded[19:20])
        resi = padded[21:26].strip()
        icode = padded[26:27].strip()
        if not resn or not resi:
            match = _REMARK_465_ROW.match(line.strip())
            if match is None:
                continue
            resn, chain, resi, icode = (
                match.group(1).upper(),
                match.group(2),
                match.group(3),
                match.group(4) or "",
            )
            chain = _norm_chain(chain)
        missing[chain].append((resn, _norm_seq_resi(resi), icode))
    return dict(missing)


def _polymer_seq_from_pdb(text: str) -> dict[str, list[tuple[str, str, str, bool]]]:
    observed: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for bucket in _residues_from_pdb(text):
        if _classify_residue(bucket) != "polymer":
            continue
        observed[bucket.chain][(_norm_seq_resi(bucket.resi), bucket.icode)] = bucket.resn
    missing = _pdb_remark_465(text)
    seqres = _pdb_seqres_names(text)
    chains = sorted({*observed, *missing, *seqres}, key=_chain_sort_key)
    out: dict[str, list[tuple[str, str, str, bool]]] = {}
    for chain in chains:
        by_key: dict[tuple[str, str], tuple[str, bool]] = {}
        for (resi, icode), resn in observed.get(chain, {}).items():
            by_key[(resi, icode)] = (resn, True)
        for resn, resi, icode in missing.get(chain, []):
            key = (resi, icode)
            if key not in by_key:
                by_key[key] = (resn, False)
        if not by_key:
            continue
        ordered_keys = sorted(by_key, key=lambda item: (_resi_sort(item[0]), item[1]))
        names = seqres.get(chain) or []
        if names and len(names) == len(ordered_keys):
            out[chain] = [
                (names[i], resi, icode, by_key[(resi, icode)][1])
                for i, (resi, icode) in enumerate(ordered_keys)
            ]
        else:
            out[chain] = [(by_key[key][0], key[0], key[1], by_key[key][1]) for key in ordered_keys]
    return out


def parse_polymer_sequences(text: str, fmt: str) -> tuple[PolymerChain, ...]:
    """Return ordered sequences per chain ID, including missing SEQRES residues."""
    fmt_l = (fmt or "pdb").lower()
    buckets = _residues_from_cif(text) if fmt_l in {"cif", "mmcif"} else _residues_from_pdb(text)
    seq_entries = polymer_sequence_entries(text, fmt)
    by_chain: dict[str, list[PolymerResidue]] = defaultdict(list)
    seq_keys: set[tuple[str, str, str]] = set()
    for chain, entries in seq_entries.items():
        for resn, resi, icode, present in entries:
            seq_keys.add((chain, resi, icode))
            kind = "polymer" if present else "missing"
            by_chain[chain].append(
                PolymerResidue(
                    chain=chain,
                    resn=resn,
                    resi=resi,
                    icode=icode,
                    letter=sequence_letter_for(resn, kind),
                    kind=kind,
                )
            )
    for bucket in buckets:
        kind = _classify_residue(bucket)
        resi = _norm_seq_resi(bucket.resi)
        key = (bucket.chain, resi, bucket.icode)
        if kind == "polymer" and key in seq_keys:
            continue
        by_chain[bucket.chain].append(
            PolymerResidue(
                chain=bucket.chain,
                resn=bucket.resn,
                resi=resi,
                icode=bucket.icode,
                letter=sequence_letter_for(bucket.resn, kind),
                kind=kind,
            )
        )
    chains: list[PolymerChain] = []
    for chain_id in sorted(by_chain, key=_chain_sort_key):
        ordered = sorted(
            by_chain[chain_id],
            key=lambda res: (_resi_sort(res.resi), res.icode, res.resn, res.kind),
        )
        if ordered:
            chains.append(PolymerChain(chain=chain_id, residues=ordered))
    return tuple(chains)


def polymer_residue_for_atom(
    chains: Iterable[PolymerChain],
    *,
    chain: str,
    resi: str | int | None,
    icode: str = "",
    structure_id: str = "",
) -> PolymerResidue | None:
    """Match a clicked atom to a polymer residue."""
    chain_s = _norm_chain(chain)
    resi_s = str(resi).strip() if resi is not None else ""
    icode_s = (icode or "").strip()
    for poly in chains:
        if structure_id and poly.structure_id and poly.structure_id != structure_id:
            continue
        if _norm_chain(poly.chain) != chain_s:
            continue
        for res in poly.residues:
            if (res.icode or "") != icode_s:
                continue
            if res.resi == resi_s or _norm_seq_resi(res.resi) == _norm_seq_resi(resi_s):
                return res
    return None


def diff_sequence_edit(old: str, new: str) -> SequenceEdit:
    """Describe mutations and deletions needed to go from *old* to *new* 1-letter strings."""
    old_s = old or ""
    new_s = new or ""
    if any(ch not in SEQUENCE_ALPHABET for ch in new_s):
        return SequenceEdit((), (), rejected_insert=False, invalid_letter=True)
    if new_s == old_s:
        return SequenceEdit((), (), rejected_insert=False, invalid_letter=False)
    mutations: list[tuple[int, str]] = []
    deletions: list[int] = []
    rejected_insert = False
    matcher = SequenceMatcher(a=old_s, b=new_s, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            rejected_insert = True
            continue
        if tag == "delete":
            deletions.extend(range(i1, i2))
            continue
        old_len = i2 - i1
        new_len = j2 - j1
        shared = min(old_len, new_len)
        for offset in range(shared):
            if old_s[i1 + offset] != new_s[j1 + offset]:
                mutations.append((i1 + offset, new_s[j1 + offset]))
        if new_len > old_len:
            rejected_insert = True
        elif old_len > new_len:
            deletions.extend(range(i1 + shared, i2))
    return SequenceEdit(
        mutations=tuple(mutations),
        deletions=tuple(sorted(set(deletions))),
        rejected_insert=rejected_insert,
        invalid_letter=False,
    )


def _pdb_residue_key(line: str) -> tuple[str, str, str] | None:
    rec = line[:6].strip().upper() if line else ""
    if rec not in {"ATOM", "HETATM"}:
        return None
    padded = line.ljust(80)
    chain = _norm_chain(padded[21:22])
    resi = padded[22:26].strip() or "0"
    icode = padded[26:27].strip()
    return (chain, resi, icode)


def rewrite_pdb_residue_names(text: str, changes: list[tuple[str, str, str, str]]) -> str:
    """Set PDB residue names for ``(chain, resi, icode, new_resn)`` records."""
    by_key = {
        (chain, resi, icode): (new_resn or "UNK").strip().upper()[:3].ljust(3)
        for chain, resi, icode, new_resn in changes
    }
    if not by_key:
        return text
    out: list[str] = []
    for line in (text or "").splitlines():
        key = _pdb_residue_key(line)
        if key is not None and key in by_key:
            padded = line.ljust(80)
            line = f"{padded[:17]}{by_key[key]}{padded[20:]}"
        out.append(line.rstrip())
    return "\n".join(out) + ("\n" if out else "")


def delete_pdb_residues(text: str, keys: set[tuple[str, str, str]]) -> str:
    """Drop ATOM/HETATM records whose ``(chain, resi, icode)`` is in *keys*."""
    if not keys:
        return text
    out: list[str] = []
    for line in (text or "").splitlines():
        key = _pdb_residue_key(line)
        if key is not None and key in keys:
            continue
        out.append(line.rstrip())
    return "\n".join(out) + ("\n" if out else "")


def _residue_key3(chain: str, resi: str, icode: str) -> tuple[str, str, str]:
    return (_norm_chain(chain), str(resi or "").strip() or "0", (icode or "").strip())


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


def attach_cif_chem_comp(
    text: str,
    chem_atoms: dict[str, tuple[CifChemAtom, ...]] | None = None,
    chem_bonds: dict[str, tuple[CifChemBond, ...]] | None = None,
) -> str:
    """Replace or append ``_chem_comp_atom`` / ``_chem_comp_bond`` loops on *text*."""
    atoms = parse_structure_atoms(text, "cif")
    have_atoms = chem_atoms if chem_atoms is not None else parse_cif_chem_comp_atoms(text)
    have_bonds = chem_bonds if chem_bonds is not None else parse_cif_chem_comp_bonds(text)
    return atoms_to_mmcif(
        atoms,
        remarks=cif_comment_remarks(text),
        chem_atoms=have_atoms,
        chem_bonds=have_bonds,
    )


def parse_structure_atoms(
    text: str, fmt: str, *, include_altlocs: bool = False
) -> tuple[StructureAtom, ...]:
    """Coordinate atoms from the first model of a PDB-like or mmCIF file."""
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        return tuple(_atoms_from_cif(text, include_altlocs=include_altlocs))
    return tuple(_atoms_from_pdb(text, include_altlocs=include_altlocs))


def pocket_view_plan(
    text: str,
    fmt: str,
    *,
    ligand_keys: Iterable[tuple[str, str, str, str]] | None = None,
    cutoff: float = POCKET_CUTOFF_ANGSTROM,
    model: int | None = None,
) -> PocketViewPlan | None:
    """Zoom selections, nearby polymer residues, and a polar-H overlay for Pocket view.

    ``ligand_keys`` are ``(chain, resn, resi, icode)``. When omitted, every ligand
    residue in the file is used. Returns ``None`` when no ligand atoms are found.
    """
    atoms = parse_structure_atoms(text, fmt)
    if not atoms:
        return None
    kinds = _residue_kinds_from_atoms(atoms)
    if ligand_keys is None:
        lig_want = {key for key, kind in kinds.items() if kind == "ligand"}
    else:
        lig_want = {
            (
                _norm_chain(chain),
                (resn or "").strip().upper(),
                str(resi).strip(),
                (icode or "").strip(),
            )
            for chain, resn, resi, icode in ligand_keys
        }
    ligand_atoms = [a for a in atoms if _atom_residue_key(a) in lig_want and not _is_hydrogen(a)]
    if not ligand_atoms:
        return None
    cutoff_sq = float(cutoff) ** 2
    lig_have = {_atom_residue_key(a) for a in ligand_atoms}
    pocket_keys: set[tuple[str, str, str, str]] = set()
    for atom in atoms:
        key = _atom_residue_key(atom)
        if kinds.get(key) != "polymer" or _is_hydrogen(atom):
            continue
        if any(_dist_sq(atom, lig) <= cutoff_sq for lig in ligand_atoms):
            pocket_keys.add(key)
    ligand_sels = tuple(
        _residue_sel_from_key(key, model=model, hetflag=True) for key in sorted(lig_have)
    )
    residue_sels = tuple(_residue_sel_from_key(key, model=model) for key in sorted(pocket_keys))
    overlay_keys = lig_have | pocket_keys
    polar_h_pdb = _polar_hydrogen_overlay_pdb(
        [a for a in atoms if _atom_residue_key(a) in overlay_keys]
    )
    return PocketViewPlan(
        ligand_sels=ligand_sels,
        residue_sels=residue_sels,
        polar_h_pdb=polar_h_pdb,
    )


def _atom_residue_key(atom: StructureAtom) -> tuple[str, str, str, str]:
    return (atom.chain, atom.resn, atom.resi, atom.icode)


def _is_hydrogen(atom: StructureAtom) -> bool:
    return atom.elem in _HYDROGEN_ELEMENTS or atom.name.strip().upper() in {"H", "D"}


def _dist_sq(a: StructureAtom, b: StructureAtom) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return dx * dx + dy * dy + dz * dz


def _residue_sel_from_key(
    key: tuple[str, str, str, str],
    *,
    model: int | None = None,
    hetflag: bool = False,
) -> dict[str, Any]:
    chain, resn, resi, icode = key
    sel: dict[str, Any] = {
        "chain": chain,
        "resn": resn,
        "resi": _resi_selection_value(resi),
    }
    if icode:
        sel["icode"] = icode
    if hetflag:
        sel["hetflag"] = True
    if model is not None:
        sel["model"] = int(model)
    return sel


def _residue_kinds_from_atoms(
    atoms: Iterable[StructureAtom],
) -> dict[tuple[str, str, str, str], str]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    for atom in atoms:
        key = _atom_residue_key(atom)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _ResidueBucket(
                chain=atom.chain, resn=atom.resn, resi=atom.resi, icode=atom.icode, het=atom.het
            )
            buckets[key] = bucket
        bucket.n_atoms += 1
        if atom.elem:
            bucket.elements.add(atom.elem)
        bucket.het = bucket.het or atom.het
    return {key: _classify_residue(bucket) for key, bucket in buckets.items()}


def _atoms_from_pdb(text: str, *, include_altlocs: bool = False) -> list[StructureAtom]:
    atoms: list[StructureAtom] = []
    saw_model = False
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if rec == "ENDMDL" and atoms:
            break
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        alt = padded[16:17].strip()
        if alt and alt not in {"A", "1"} and not include_altlocs:
            continue
        name = padded[12:16].strip()
        resn = padded[17:20].strip() or name[:3]
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip()
        try:
            x = float(padded[30:38])
            y = float(padded[38:46])
            z = float(padded[46:54])
        except ValueError:
            continue
        occ = _optional_float(padded[54:60], 1.0)
        bfac = _optional_float(padded[60:66], 0.0)
        elem = padded[76:78].strip() or "".join(ch for ch in name if ch.isalpha())[:2]
        atoms.append(
            StructureAtom(
                chain=chain,
                resn=resn.upper(),
                resi=resi,
                icode=icode,
                name=name,
                elem=elem.upper(),
                x=x,
                y=y,
                z=z,
                het=rec == "HETATM",
                altloc=alt,
                occupancy=occ,
                bfactor=bfac,
            )
        )
    return atoms


def _atoms_from_cif(text: str, *, include_altlocs: bool = False) -> list[StructureAtom]:
    atoms: list[StructureAtom] = []
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_atom_site.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_group = _cif_col(index, "group_PDB")
        i_symbol = _cif_col(index, "type_symbol")
        i_atom = _cif_col(index, "auth_atom_id", "label_atom_id")
        i_comp = _cif_col(index, "auth_comp_id", "label_comp_id")
        i_asym = _cif_col(index, "auth_asym_id", "label_asym_id")
        i_seq = _cif_col(index, "auth_seq_id", "label_seq_id")
        i_icode = _cif_col(index, "pdbx_PDB_ins_code")
        i_model = _cif_col(index, "pdbx_PDB_model_num")
        i_x = _cif_col(index, "Cartn_x")
        i_y = _cif_col(index, "Cartn_y")
        i_z = _cif_col(index, "Cartn_z")
        i_alt = _cif_col(index, "label_alt_id")
        i_occ = _cif_col(index, "occupancy")
        i_b = _cif_col(index, "B_iso_or_equiv")
        if i_x is None or i_y is None or i_z is None:
            continue
        first_model = ""
        for row in rows:
            if i_model is not None:
                model = _cif_cell(row, i_model, "1") or "1"
                if not first_model:
                    first_model = model
                elif model != first_model:
                    continue
            alt_id = _cif_cell(row, i_alt)
            if alt_id and alt_id not in {".", "?", "A", "1"} and not include_altlocs:
                continue
            try:
                x = float(_cif_cell(row, i_x, "nan"))
                y = float(_cif_cell(row, i_y, "nan"))
                z = float(_cif_cell(row, i_z, "nan"))
            except ValueError:
                continue
            if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z):
                continue
            name = _cif_cell(row, i_atom) or "X"
            resn = _cif_cell(row, i_comp, "UNK").upper() or "UNK"
            chain = _norm_chain(_cif_cell(row, i_asym, "?") or "?")
            resi = _cif_cell(row, i_seq, "0") or "0"
            icode = _cif_cell(row, i_icode)
            elem = _cif_cell(row, i_symbol) or "".join(ch for ch in name if ch.isalpha())[:2]
            group = _cif_cell(row, i_group, "ATOM")
            occ_raw = _cif_cell(row, i_occ, "1.0") if i_occ is not None else "1.0"
            b_raw = _cif_cell(row, i_b, "0.0") if i_b is not None else "0.0"
            alt = "" if alt_id in {".", "?", None} else str(alt_id)
            atoms.append(
                StructureAtom(
                    chain=chain,
                    resn=resn,
                    resi=str(resi),
                    icode=icode,
                    name=name,
                    elem=elem.upper(),
                    x=x,
                    y=y,
                    z=z,
                    het=str(group).upper().startswith("HET"),
                    altloc=alt,
                    occupancy=_optional_float(occ_raw, 1.0),
                    bfactor=_optional_float(b_raw, 0.0),
                )
            )
    return atoms


def _polar_hydrogen_overlay_pdb(atoms: list[StructureAtom]) -> str:
    """PDB of polar hydrogens plus their parent N/O/S/F atoms for a 3Dmol overlay."""
    if not atoms:
        return ""
    hydrogens = _existing_polar_hydrogens(atoms)
    hydrogens.extend(_rdkit_polar_hydrogens(_pdb_from_atoms(atoms)))
    hydrogens = _unique_atoms_by_xyz(hydrogens)
    if not hydrogens:
        return ""
    parents = [a for a in atoms if a.elem in POLAR_HEAVY_ELEMENTS]
    return _pdb_from_atoms(parents + hydrogens)


def _existing_polar_hydrogens(atoms: list[StructureAtom]) -> list[StructureAtom]:
    heavies = [a for a in atoms if a.elem in POLAR_HEAVY_ELEMENTS]
    bond_sq = _POLAR_H_BOND_ANGSTROM**2
    out: list[StructureAtom] = []
    for atom in atoms:
        if not _is_hydrogen(atom):
            continue
        if any(_dist_sq(atom, heavy) <= bond_sq for heavy in heavies):
            out.append(replace(atom, elem="H", het=True))
    return out


def _rdkit_polar_hydrogens(pdb_block: str) -> list[StructureAtom]:
    if not pdb_block.strip():
        return []
    try:
        from rdkit import Chem
    except ImportError:
        return []
    try:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, proximityBonding=True, sanitize=False)
    except TypeError:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, sanitize=False)
    except Exception:
        return []
    if mol is None or mol.GetNumAtoms() == 0:
        return []
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        pass
    try:
        mol_h = Chem.AddHs(mol, addCoords=True)
    except Exception:
        return []
    if mol_h is None or mol_h.GetNumConformers() == 0:
        return []
    conf = mol_h.GetConformer()
    polar = set(POLAR_HEAVY_ELEMENTS)
    out: list[StructureAtom] = []
    for atom in mol_h.GetAtoms():
        if atom.GetAtomicNum() != 1:
            continue
        neighbors = atom.GetNeighbors()
        if not neighbors or neighbors[0].GetSymbol() not in polar:
            continue
        parent = neighbors[0]
        info = atom.GetPDBResidueInfo() or parent.GetPDBResidueInfo()
        pos = conf.GetAtomPosition(atom.GetIdx())
        chain = "?"
        resn = "UNK"
        resi = "0"
        icode = ""
        name = "H"
        het = True
        if info is not None:
            chain = _norm_chain(info.GetChainId())
            resn = (info.GetResidueName() or "UNK").strip().upper() or "UNK"
            resi = str(info.GetResidueNumber())
            icode = (info.GetInsertionCode() or "").strip()
            name = (info.GetName() or "H").strip() or "H"
            het = bool(info.GetIsHeteroAtom())
        out.append(
            StructureAtom(
                chain=chain,
                resn=resn,
                resi=resi,
                icode=icode,
                name=name,
                elem="H",
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                het=het,
            )
        )
    return out


def _unique_atoms_by_xyz(atoms: Iterable[StructureAtom]) -> list[StructureAtom]:
    seen: set[tuple[float, float, float]] = set()
    out: list[StructureAtom] = []
    for atom in atoms:
        key = (round(atom.x, 3), round(atom.y, 3), round(atom.z, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(atom)
    return out


def _pdb_from_atoms(atoms: Iterable[StructureAtom]) -> str:
    lines = [_format_pdb_atom(i, atom) for i, atom in enumerate(atoms, start=1)]
    if not lines:
        return ""
    return "\n".join(lines) + "\nEND\n"


def _format_pdb_atom(serial: int, atom: StructureAtom) -> str:
    rec = "HETATM" if atom.het else "ATOM  "
    raw_name = (atom.name or atom.elem or "X").strip()
    if len(raw_name) < 4 and len(atom.elem or "") <= 1:
        name_field = f" {raw_name:<3s}"[:4]
    else:
        name_field = f"{raw_name:<4s}"[:4]
    resn = (atom.resn or "UNK")[:3].rjust(3)
    chain = (atom.chain or " ")[:1] or " "
    try:
        resi_i = int(atom.resi)
    except (TypeError, ValueError):
        resi_i = 0
    icode = (atom.icode or " ")[:1] or " "
    elem = (atom.elem or "")[:2]
    return (
        f"{rec}{serial:5d} {name_field} {resn} {chain}{resi_i:4d}{icode}"
        f"   {atom.x:8.3f}{atom.y:8.3f}{atom.z:8.3f}  1.00  0.00          {elem:>2}"
    )
