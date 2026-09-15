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


"""Residue tables and dataclasses for crystallographic inventories."""

from __future__ import annotations


from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

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


def _resi_selection_value(resi: str) -> int | str:
    try:
        return int(resi)
    except (TypeError, ValueError):
        return resi


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


def _optional_float(text: str, default: float) -> float:
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return default


def _norm_chain(chain: str | None) -> str:
    raw = (chain or "").strip()
    return raw if raw else "?"


def _residue_key3(chain: str, resi: str, icode: str) -> tuple[str, str, str]:
    return (_norm_chain(chain), str(resi or "").strip() or "0", (icode or "").strip())


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
