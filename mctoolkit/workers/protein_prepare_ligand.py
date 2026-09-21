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

"""Ligand bond orders, Uni-pKa protomers, and hydrogens for Protein Prepare."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, rdmolops

from ..protein.structure_components import (
    _pdb_residue_key,
    parse_cif_chem_comp_atoms,
    parse_cif_chem_comp_bonds,
)

ResidueKey = tuple[str, str, str]

# Distance-dependent dielectric ε = 4r (Å); Coulomb constant in kcal mol⁻¹ e⁻² Å.
_COULOMB_K = 332.06371
_DIELECTRIC_SLOPE = 4.0
_POCKET_CUTOFF_A = 12.0
_MIN_CONTACT_A = 1.5
_KT_KCAL = 0.592  # 298 K
_MIN_AQUEOUS_PCT = 5.0


@dataclass(frozen=True)
class LigandProtomerChoice:
    """Selected ligand ionization state at the Prepare pH."""

    mol: Chem.Mol
    smiles: str
    charge: int
    aqueous_pct: float
    pocket_pct: float | None = None
    pocket_energy_kcal: float | None = None
    used_pocket: bool = False

    def remark_line(self) -> str:
        smi = self.smiles if len(self.smiles) <= 48 else self.smiles[:45] + "..."
        pocket = f" POCKET {self.pocket_pct:.0f}%" if self.pocket_pct is not None else ""
        src = "POCKET" if self.used_pocket else "AQUEOUS"
        return f"3C UNIPKA LIGAND {src} Q={self.charge:+d} AQ {self.aqueous_pct:.0f}%{pocket} {smi}"


def load_bond_order_template(*, smiles: str = "", ref_path: str = "") -> Chem.Mol | None:
    """Load a bond-order template from SMILES or an SDF/MOL2/MOL file."""
    path = (ref_path or "").strip()
    if path:
        src = Path(path).expanduser()
        if not src.is_file():
            raise ValueError(f"Ligand bond-order file not found: {src}")
        suffix = src.suffix.lower()
        mol = None
        if suffix in {".sdf", ".sd", ".mol"}:
            mol = Chem.MolFromMolFile(str(src), removeHs=False, sanitize=False)
            if mol is None and suffix in {".sdf", ".sd"}:
                suppl = Chem.SDMolSupplier(str(src), removeHs=False, sanitize=False)
                mol = next((m for m in suppl if m is not None), None)
        elif suffix in {".mol2", ".ml2"}:
            mol = Chem.MolFromMol2File(str(src), removeHs=False, sanitize=False)
        else:
            raise ValueError("Ligand bond-order file must be SDF, MOL, or MOL2.")
        if mol is None or mol.GetNumAtoms() == 0:
            raise ValueError(f"Could not read a molecule from {src}.")
        try:
            Chem.SanitizeMol(mol)
        except Exception as exc:
            raise ValueError(f"Could not sanitize ligand template {src}: {exc}") from exc
        return mol
    smi = (smiles or "").strip()
    if not smi:
        return None
    mol = Chem.MolFromSmiles(smi)
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError(f"Could not parse ligand SMILES: {smi}")
    return mol


def apply_bond_order_template(pdb_mol: Chem.Mol, template: Chem.Mol) -> Chem.Mol:
    """Copy Kekulé/aromatic bond orders from *template* onto PDB coordinates."""
    pdb_heavy = Chem.RemoveHs(Chem.Mol(pdb_mol), sanitize=False)
    tmpl_heavy = Chem.RemoveHs(Chem.Mol(template), sanitize=False)
    try:
        Chem.SanitizeMol(tmpl_heavy)
    except Exception as exc:
        raise ValueError(f"Ligand bond-order template is not a valid molecule: {exc}") from exc
    if pdb_heavy.GetNumAtoms() != tmpl_heavy.GetNumAtoms():
        raise ValueError(
            "Ligand atom count does not match the bond-order template "
            f"({pdb_heavy.GetNumAtoms()} PDB heavy atoms vs "
            f"{tmpl_heavy.GetNumAtoms()} in SMILES/SDF)."
        )
    try:
        return AllChem.AssignBondOrdersFromTemplate(tmpl_heavy, pdb_heavy)
    except Exception as exc:
        raise ValueError(
            "Could not map the bond-order template onto the crystallographic ligand. "
            "Check that the SMILES or SDF is the same molecule as the PDB HETATM."
        ) from exc


def assign_bond_orders_from_geometry(mol: Chem.Mol, *, charge: int = 0) -> Chem.Mol:
    """Infer connectivity and bond orders from 3D coordinates (RDKit xyz2mol)."""
    try:
        from rdkit.Chem import rdDetermineBonds
    except ImportError as exc:
        raise ValueError(
            "RDKit rdDetermineBonds is required to guess ligand bond orders. "
            "Provide SMILES or an SDF/MOL2 instead."
        ) from exc
    work = Chem.Mol(mol)
    try:
        rdDetermineBonds.DetermineBondOrders(work, charge=int(charge))
        Chem.SanitizeMol(work)
        return work
    except Exception:
        pass
    xyz = Chem.RWMol()
    for atom in mol.GetAtoms():
        xyz.AddAtom(Chem.Atom(atom.GetAtomicNum()))
    if mol.GetNumConformers() == 0:
        raise ValueError("Ligand has no coordinates for bond-order assignment.")
    xyz.AddConformer(mol.GetConformer(), assignId=True)
    geo = xyz.GetMol()
    try:
        rdDetermineBonds.DetermineBonds(geo, charge=int(charge))
        Chem.SanitizeMol(geo)
        return geo
    except Exception as exc:
        raise ValueError(
            "Could not guess ligand bond orders from coordinates. "
            "Provide ligand SMILES or an SDF/MOL2 with correct bond orders."
        ) from exc


def _cif_rdkit_bond_type(token: str):
    key = (token or "").strip().lower()[:4]
    if key in {"arom"}:
        return Chem.BondType.AROMATIC
    if key in {"doub", "delo"}:
        return Chem.BondType.DOUBLE
    if key in {"trip", "quad"}:
        return Chem.BondType.TRIPLE
    return Chem.BondType.SINGLE


def mol_from_cif_component(text: str, resn: str) -> Chem.Mol | None:
    """Build an RDKit mol from mmCIF ``_chem_comp_atom`` / ``_chem_comp_bond``.

    Hydrogens and leaving atoms from the CCD table are included when present.
    Returns ``None`` when that component has no usable connectivity.
    """
    from rdkit.Chem import rdchem

    comp = (resn or "").strip().upper()
    if not comp:
        return None
    atoms = parse_cif_chem_comp_atoms(text).get(comp)
    bonds = parse_cif_chem_comp_bonds(text).get(comp)
    if not atoms or not bonds:
        return None
    rw = Chem.RWMol()
    idx: dict[str, int] = {}
    for atom in atoms:
        if atom.leaving:
            continue
        try:
            anum = rdchem.GetPeriodicTable().GetAtomicNumber(atom.symbol.title())
        except Exception:
            anum = 6
        if anum <= 0:
            continue
        rd_atom = Chem.Atom(anum)
        if atom.charge:
            rd_atom.SetFormalCharge(int(atom.charge))
        idx[atom.atom_id] = rw.AddAtom(rd_atom)
    if len(idx) < 2:
        return None
    n_bonds = 0
    for bond in bonds:
        a = idx.get(bond.atom_id_1)
        b = idx.get(bond.atom_id_2)
        if a is None or b is None or a == b:
            continue
        if rw.GetBondBetweenAtoms(a, b) is not None:
            continue
        rw.AddBond(a, b, _cif_rdkit_bond_type(bond.order_token))
        n_bonds += 1
    if n_bonds == 0:
        return None
    mol = rw.GetMol()
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        try:
            Chem.SanitizeMol(
                mol,
                sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL ^ Chem.SanitizeFlags.SANITIZE_KEKULIZE,
            )
        except Exception:
            return None
    if mol.GetNumAtoms() == 0:
        return None
    return mol


def mols_from_cif_ligands(text: str, resns: Iterable[str]) -> dict[str, Chem.Mol]:
    """RDKit parents for ligand residue names that have CIF connectivity."""
    out: dict[str, Chem.Mol] = {}
    for resn in resns:
        key = (resn or "").strip().upper()
        if not key or key in out:
            continue
        mol = mol_from_cif_component(text, key)
        if mol is not None:
            out[key] = mol
    return out


def mol_from_ligand_pdb(
    block: str,
    *,
    template: Chem.Mol | None = None,
) -> Chem.Mol:
    """Build a sanitized RDKit mol for one ligand residue PDB block."""
    try:
        mol = Chem.MolFromPDBBlock(block, removeHs=False, proximityBonding=True, sanitize=False)
    except TypeError:
        mol = Chem.MolFromPDBBlock(block, removeHs=False, sanitize=False)
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError("Could not read ligand coordinates from the PDB.")
    charge = 0
    if template is not None:
        charge = int(Chem.GetFormalCharge(Chem.RemoveHs(template, sanitize=False)))
        return apply_bond_order_template(mol, template)
    return assign_bond_orders_from_geometry(mol, charge=charge)


def ligand_residue_blocks(
    text: str, keys: set[ResidueKey], *, fmt: str = "pdb"
) -> list[tuple[ResidueKey, str, str]]:
    """Return ``(key, resn, pdb_block)`` for each requested ligand residue."""
    if (fmt or "pdb").lower() in {"cif", "mmcif"}:
        return _ligand_residue_blocks_cif(text, keys)
    wanted = set(keys)
    grouped: dict[ResidueKey, list[str]] = defaultdict(list)
    resn_by_key: dict[ResidueKey, str] = {}
    for line in (text or "").splitlines():
        raw = _pdb_residue_key(line)
        if raw is None or raw not in wanted:
            continue
        grouped[raw].append(line.rstrip())
        padded = line.ljust(80)
        resn_by_key[raw] = padded[17:20].strip() or resn_by_key.get(raw, "LIG")
    out: list[tuple[ResidueKey, str, str]] = []
    for key in grouped:
        lines = _prefer_altloc_lines(grouped[key])
        block = "\n".join(lines) + "\nEND\n"
        out.append((key, resn_by_key.get(key, "LIG"), block))
    return out


def _ligand_residue_blocks_cif(
    text: str, keys: set[ResidueKey]
) -> list[tuple[ResidueKey, str, str]]:
    from ..protein.structure_components import _norm_chain, _pdb_from_atoms, parse_structure_atoms

    wanted = set(keys)
    grouped: dict[ResidueKey, list] = defaultdict(list)
    resn_by_key: dict[ResidueKey, str] = {}
    for atom in parse_structure_atoms(text, "cif"):
        key = (
            _norm_chain(atom.chain),
            str(atom.resi or "").strip() or "0",
            (atom.icode or "").strip(),
        )
        if key not in wanted:
            continue
        grouped[key].append(atom)
        resn_by_key[key] = atom.resn or resn_by_key.get(key, "LIG")
    out: list[tuple[ResidueKey, str, str]] = []
    for key, atoms in grouped.items():
        out.append((key, resn_by_key.get(key, "LIG"), _pdb_from_atoms(atoms)))
    return out


def _pdb_altloc(line: str) -> str:
    padded = line.ljust(80)
    return padded[16].strip()


def _prefer_altloc_lines(lines: list[str]) -> list[str]:
    """Keep one occupancy copy so SMILES heavy-atom counts can match the crystal."""
    if len(lines) < 2:
        return lines
    alts = {_pdb_altloc(ln) for ln in lines}
    if len(alts) <= 1:
        return lines
    if "" in alts:
        return [ln for ln in lines if not _pdb_altloc(ln)]
    if "A" in alts:
        return [ln for ln in lines if _pdb_altloc(ln) == "A"]
    prefer = sorted(a for a in alts if a)[0]
    return [ln for ln in lines if _pdb_altloc(ln) == prefer]


def _atom_name(atom: Chem.Atom, used: set[str]) -> str:
    info = atom.GetPDBResidueInfo()
    if info is not None:
        name = (info.GetName() or "").strip()
        if name:
            return name[:4]
    elem = atom.GetSymbol() or "C"
    base = elem.upper()[:4]
    if base not in used:
        return base
    for i in range(1, 1000):
        cand = f"{elem}{i}"[:4]
        if cand not in used:
            return cand
    return elem[:4]


def _format_pdb_atom_name(name: str) -> str:
    """PDB atom name in columns 13–16 (leading space when the name is shorter than 4)."""
    raw = (name or "").strip()[:4]
    if len(raw) == 4:
        return raw
    return f" {raw:<3s}"[:4]


def _hetatm_line(
    serial: int,
    name: str,
    resn: str,
    chain: str,
    resi: str,
    icode: str,
    x: float,
    y: float,
    z: float,
    elem: str,
) -> str:
    try:
        resi_i = int(str(resi).strip())
        resi_s = f"{resi_i:4d}"
    except (TypeError, ValueError):
        resi_s = f"{str(resi).strip():>4s}"[:4]
    chain_s = (chain or " ")[:1] or " "
    icode_s = (icode or " ")[:1] or " "
    name_s = _format_pdb_atom_name(name)
    resn_s = f"{(resn or 'LIG'):>3s}"[:3]
    elem_s = f"{(elem or ''):>2s}"[:2]
    altloc = " "
    return (
        f"HETATM{serial:5d} {name_s}{altloc}{resn_s} {chain_s}{resi_s}{icode_s}   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {elem_s}"
    )


def mol_to_hetatm_lines(
    mol: Chem.Mol,
    *,
    chain: str,
    resn: str,
    resi: str,
    icode: str,
    serial_start: int,
) -> list[str]:
    """Format an RDKit ligand (with explicit H) as HETATM records."""
    if mol.GetNumConformers() == 0:
        raise ValueError("Ligand has no 3D coordinates.")
    conf = mol.GetConformer()
    used_names: set[str] = set()
    lines: list[str] = []
    serial = int(serial_start)
    for atom in mol.GetAtoms():
        name = _atom_name(atom, used_names)
        used_names.add(name)
        pos = conf.GetAtomPosition(atom.GetIdx())
        lines.append(
            _hetatm_line(
                serial,
                name,
                resn,
                chain,
                resi,
                icode,
                float(pos.x),
                float(pos.y),
                float(pos.z),
                atom.GetSymbol(),
            )
        )
        serial += 1
    return lines


def _rdkit_cif_bond(bond) -> tuple[str, int, bool]:
    aromatic = bool(bond.GetIsAromatic())
    if aromatic:
        return "arom", 2, True
    btype = bond.GetBondType()
    if btype == Chem.BondType.DOUBLE:
        return "doub", 2, False
    if btype == Chem.BondType.TRIPLE:
        return "trip", 3, False
    return "sing", 1, False


def chem_comp_tables_from_mols(
    mols: Iterable[Chem.Mol],
) -> tuple[dict[str, tuple], dict[str, tuple]]:
    """CCD-style ``_chem_comp_atom`` / ``_chem_comp_bond`` tables from RDKit ligands."""
    from ..protein.structure_components import CifChemAtom, CifChemBond

    atoms_out: dict[str, list] = {}
    bonds_out: dict[str, list] = {}
    for mol in mols:
        if mol is None:
            continue
        try:
            n_atoms = mol.GetNumAtoms()
        except Exception:
            continue
        if n_atoms == 0:
            continue
        resn = "LIG"
        if mol.HasProp("_Name"):
            resn = (mol.GetProp("_Name") or "LIG").strip().upper() or "LIG"
        if resn in atoms_out:
            continue
        used: set[str] = set()
        names: list[str] = []
        atoms: list = []
        for atom in mol.GetAtoms():
            name = _atom_name(atom, used)
            used.add(name)
            names.append(name)
            atoms.append(
                CifChemAtom(
                    atom_id=name,
                    symbol=atom.GetSymbol() or "C",
                    charge=int(atom.GetFormalCharge()),
                    aromatic=bool(atom.GetIsAromatic()),
                )
            )
        bonds: list = []
        for bond in mol.GetBonds():
            token, order, aromatic = _rdkit_cif_bond(bond)
            bonds.append(
                CifChemBond(
                    atom_id_1=names[bond.GetBeginAtomIdx()],
                    atom_id_2=names[bond.GetEndAtomIdx()],
                    order=order,
                    order_token=token,
                    aromatic=aromatic,
                )
            )
        atoms_out[resn] = atoms
        bonds_out[resn] = bonds
    return (
        {key: tuple(vals) for key, vals in atoms_out.items()},
        {key: tuple(vals) for key, vals in bonds_out.items()},
    )


def _max_atom_serial(text: str) -> int:
    n = 0
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec not in {"ATOM", "HETATM"}:
            continue
        try:
            n = max(n, int(line[6:11]))
        except (TypeError, ValueError):
            continue
    return n


def mol_to_structure_atoms(
    mol: Chem.Mol,
    *,
    chain: str,
    resn: str,
    resi: str,
    icode: str,
) -> list:
    """Coordinate atoms for rewriting an mmCIF ligand residue."""
    from ..protein.structure_components import StructureAtom

    if mol.GetNumConformers() == 0:
        raise ValueError("Ligand has no 3D coordinates.")
    conf = mol.GetConformer()
    used_names: set[str] = set()
    atoms: list = []
    for atom in mol.GetAtoms():
        name = _atom_name(atom, used_names)
        used_names.add(name)
        pos = conf.GetAtomPosition(atom.GetIdx())
        atoms.append(
            StructureAtom(
                chain=chain,
                resn=resn,
                resi=str(resi),
                icode=icode or "",
                name=name,
                elem=(atom.GetSymbol() or "C").upper(),
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                het=True,
            )
        )
    return atoms


def prepare_ligands_for_gaff(
    pdb_text: str,
    ligand_keys: set[ResidueKey],
    *,
    smiles: str = "",
    ref_path: str = "",
    template: Chem.Mol | None = None,
    templates_by_resn: dict[str, Chem.Mol] | None = None,
    fmt: str = "pdb",
) -> tuple[list[Chem.Mol], str]:
    """
    Assign bond orders, add explicit hydrogens, and rewrite ligand coordinates.

    Returns RDKit mols (with H) matching the rewritten structure, plus the new file text.
    """
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        return _prepare_ligands_for_gaff_cif(
            pdb_text,
            ligand_keys,
            smiles=smiles,
            ref_path=ref_path,
            template=template,
            templates_by_resn=templates_by_resn,
        )
    from ..protein.structure_components import delete_pdb_residues

    if not ligand_keys:
        return [], pdb_text
    if template is None:
        template = load_bond_order_template(smiles=smiles, ref_path=ref_path)
    residues = ligand_residue_blocks(pdb_text, ligand_keys, fmt="pdb")
    if not residues:
        return [], pdb_text
    mols: list[Chem.Mol] = []
    replacement_lines: list[str] = []
    serial = _max_atom_serial(pdb_text) + 1
    by_resn = templates_by_resn or {}
    for key, resn, block in residues:
        res_template = template or by_resn.get((resn or "").upper())
        mol = mol_from_ligand_pdb(block, template=res_template)
        try:
            mol_h = Chem.AddHs(mol, addCoords=True)
            Chem.SanitizeMol(mol_h)
        except Exception as exc:
            raise ValueError(f"Could not add hydrogens to ligand {resn} {key[1]}: {exc}") from exc
        mol_h.SetProp("_Name", resn)
        mols.append(mol_h)
        chain, resi, icode = key
        new_lines = mol_to_hetatm_lines(
            mol_h,
            chain=chain,
            resn=resn,
            resi=resi,
            icode=icode,
            serial_start=serial,
        )
        serial += len(new_lines)
        replacement_lines.extend(new_lines)
    stripped = delete_pdb_residues(pdb_text, ligand_keys)
    lines = [line.rstrip() for line in stripped.splitlines()]
    end_i = next((i for i, line in enumerate(lines) if line.startswith("END")), len(lines))
    merged = lines[:end_i] + replacement_lines + lines[end_i:]
    return mols, "\n".join(merged) + "\n"


def _prepare_ligands_for_gaff_cif(
    cif_text: str,
    ligand_keys: set[ResidueKey],
    *,
    smiles: str = "",
    ref_path: str = "",
    template: Chem.Mol | None = None,
    templates_by_resn: dict[str, Chem.Mol] | None = None,
) -> tuple[list[Chem.Mol], str]:
    from ..protein.structure_components import (
        _residue_key3,
        atoms_to_mmcif,
        cif_comment_remarks,
        parse_cif_chem_comp_atoms,
        parse_cif_chem_comp_bonds,
        parse_structure_atoms,
    )

    if not ligand_keys:
        return [], cif_text
    if template is None:
        template = load_bond_order_template(smiles=smiles, ref_path=ref_path)
    residues = ligand_residue_blocks(cif_text, ligand_keys, fmt="cif")
    if not residues:
        return [], cif_text
    mols: list[Chem.Mol] = []
    replacements: dict[ResidueKey, list] = {}
    by_resn = templates_by_resn or {}
    for key, resn, block in residues:
        res_template = template or by_resn.get((resn or "").upper())
        mol = mol_from_ligand_pdb(block, template=res_template)
        try:
            mol_h = Chem.AddHs(mol, addCoords=True)
            Chem.SanitizeMol(mol_h)
        except Exception as exc:
            raise ValueError(f"Could not add hydrogens to ligand {resn} {key[1]}: {exc}") from exc
        mol_h.SetProp("_Name", resn)
        mols.append(mol_h)
        chain, resi, icode = key
        replacements[key] = mol_to_structure_atoms(
            mol_h, chain=chain, resn=resn, resi=resi, icode=icode
        )
    drop = set(replacements)
    kept = [
        atom
        for atom in parse_structure_atoms(cif_text, "cif")
        if _residue_key3(atom.chain, atom.resi, atom.icode) not in drop
    ]
    new_atoms = kept + [atom for atoms in replacements.values() for atom in atoms]
    chem_atoms = parse_cif_chem_comp_atoms(cif_text)
    chem_bonds = parse_cif_chem_comp_bonds(cif_text)
    remaining = {atom.resn.upper() for atom in new_atoms if atom.resn}
    mol_atoms, mol_bonds = chem_comp_tables_from_mols(mols)
    chem_atoms = {comp: rows for comp, rows in chem_atoms.items() if comp in remaining}
    chem_bonds = {comp: rows for comp, rows in chem_bonds.items() if comp in remaining}
    chem_atoms.update(mol_atoms)
    chem_bonds.update(mol_bonds)
    return mols, atoms_to_mmcif(
        new_atoms,
        remarks=cif_comment_remarks(cif_text),
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
    )


def _sybyl_type(atom: Chem.Atom) -> str:
    z = atom.GetAtomicNum()
    if atom.GetIsAromatic():
        if z == 6:
            return "C.ar"
        if z == 7:
            return "N.ar"
    hyb = atom.GetHybridization()
    if z == 6:
        if hyb == Chem.HybridizationType.SP2:
            return "C.2"
        if hyb == Chem.HybridizationType.SP:
            return "C.1"
        return "C.3"
    if z == 7:
        if atom.GetFormalCharge() == 1:
            return "N.4"
        if hyb == Chem.HybridizationType.SP2:
            return "N.2"
        return "N.3"
    if z == 8:
        if atom.GetFormalCharge() == -1:
            return "O.co2"
        if hyb == Chem.HybridizationType.SP2:
            return "O.2"
        return "O.3"
    if z == 16:
        return "S.2" if hyb == Chem.HybridizationType.SP2 else "S.3"
    if z == 15:
        return "P.3"
    return atom.GetSymbol() or "Du"


def _gasteiger_charge(atom: Chem.Atom) -> float:
    try:
        q = float(atom.GetDoubleProp("_GasteigerCharge"))
    except Exception:
        return 0.0
    if q != q:  # NaN
        return 0.0
    return q


def parse_pqr_atoms(
    text: str,
) -> list[tuple[ResidueKey, str, float, float, float, float]]:
    """Parse PQR ATOM/HETATM records as ``(key, name, x, y, z, charge)``."""
    from ..protein.structure_components import _norm_chain

    out: list[tuple[ResidueKey, str, float, float, float, float]] = []
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec not in {"ATOM", "HETATM"}:
            continue
        try:
            name = line[12:16].strip()
            chain = _norm_chain(line[21:22])
            resi = line[22:26].strip() or "0"
            icode = line[26:27].strip()
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            rest = line[54:].split()
            charge = float(rest[0])
        except (TypeError, ValueError, IndexError):
            parts = line.split()
            if len(parts) < 11:
                continue
            try:
                name = parts[2]
                chain = _norm_chain(parts[4])
                resi = parts[5]
                icode = ""
                x = float(parts[6])
                y = float(parts[7])
                z = float(parts[8])
                charge = float(parts[9])
            except (TypeError, ValueError, IndexError):
                continue
        out.append(((chain, resi, icode), name, x, y, z, charge))
    return out


def ligand_pocket_coulomb_kcal(
    mol: Chem.Mol,
    pqr_atoms: list[tuple[ResidueKey, str, float, float, float, float]],
    ligand_keys: set[ResidueKey],
) -> float:
    """Coulomb energy of *mol* in a PQR field, excluding ligand residues.

    Uses Gasteiger charges on the ligand and a distance-dependent dielectric
    ε = 4r. This is a pocket electrostatic *shift*, not a PB/GBSA free energy.
    """
    if mol.GetNumConformers() == 0 or not pqr_atoms:
        return 0.0
    work = Chem.Mol(mol)
    try:
        AllChem.ComputeGasteigerCharges(work)
    except Exception:
        return 0.0
    conf = work.GetConformer()
    lig: list[tuple[float, float, float, float]] = []
    for atom in work.GetAtoms():
        q = _gasteiger_charge(atom)
        if abs(q) < 1e-6:
            continue
        pos = conf.GetAtomPosition(atom.GetIdx())
        lig.append((q, float(pos.x), float(pos.y), float(pos.z)))
    if not lig:
        return 0.0
    skip = set(ligand_keys)
    energy = 0.0
    cutoff = _POCKET_CUTOFF_A
    min_r = _MIN_CONTACT_A
    k = _COULOMB_K / _DIELECTRIC_SLOPE
    for key, _name, x, y, z, qj in pqr_atoms:
        if key in skip or abs(qj) < 1e-6:
            continue
        for qi, xi, yi, zi in lig:
            dx = xi - x
            dy = yi - y
            dz = zi - z
            r2 = dx * dx + dy * dy + dz * dz
            if r2 > cutoff * cutoff:
                continue
            r = r2**0.5
            if r < min_r:
                r = min_r
            energy += k * qi * qj / r2
    return energy


def write_ligand_mol2(mol: Chem.Mol, path: Path, *, resn: str, resi: str) -> None:
    """Write a pdb2pqr-compatible MOL2 (unique names, matching residue id)."""
    if mol.GetNumConformers() == 0:
        raise ValueError("Ligand has no 3D coordinates for MOL2 export.")
    conf = mol.GetConformer()
    used: set[str] = set()
    atom_lines: list[str] = []
    try:
        resi_i = int(str(resi).strip())
    except (TypeError, ValueError):
        resi_i = 1
    resn_s = (resn or "LIG")[:4]
    AllChem.ComputeGasteigerCharges(mol)
    for i, atom in enumerate(mol.GetAtoms(), start=1):
        name = _atom_name(atom, used)
        used.add(name)
        pos = conf.GetAtomPosition(atom.GetIdx())
        q = _gasteiger_charge(atom)
        atom_lines.append(
            f"{i:7d} {name:<4s} {pos.x:10.4f} {pos.y:10.4f} {pos.z:10.4f} "
            f"{_sybyl_type(atom):<6s} {resi_i:4d} {resn_s:<4s} {q:8.4f}"
        )
    bond_lines: list[str] = []
    bidx = 1
    for bond in mol.GetBonds():
        a = bond.GetBeginAtomIdx() + 1
        b = bond.GetEndAtomIdx() + 1
        if bond.GetIsAromatic():
            btype = "ar"
        else:
            order = int(round(bond.GetBondTypeAsDouble() or 1.0))
            btype = str(min(max(order, 1), 3))
        bond_lines.append(f"{bidx:6d} {a:4d} {b:4d} {btype}")
        bidx += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "@<TRIPOS>MOLECULE",
        resn_s,
        f"{len(atom_lines)} {len(bond_lines)} 1 0 0",
        "SMALL",
        "USER_CHARGES",
        "",
        "@<TRIPOS>ATOM",
        *atom_lines,
        "@<TRIPOS>BOND",
        *bond_lines,
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")


def ligand_ionization_ensemble(template: Chem.Mol, ensemble=None):
    """Score a Uni-pKa ensemble for *template*, or return a precomputed *ensemble*."""
    from ..ionization.unipka_ensembles import predict_ionization_ensemble, unipka_import_error

    if ensemble is not None:
        return ensemble
    err = unipka_import_error()
    if err:
        raise ValueError(err)
    scored = predict_ionization_ensemble(template)
    if scored is None:
        raise ValueError(
            "Uni-pKa did not return an ionization ensemble for the ligand. "
            "Check the SMILES/SDF and the pka extra (unipkainfer)."
        )
    return scored


def choose_ligand_protomer(
    template: Chem.Mol,
    *,
    ph: float,
    pdb_block: str = "",
    pqr_text: str = "",
    ligand_keys: set[ResidueKey] | None = None,
    ensemble=None,
    min_aqueous_pct: float = _MIN_AQUEOUS_PCT,
) -> LigandProtomerChoice:
    """Pick the ligand protomer at *ph*, optionally reweighted in the PQR pocket.

    Uni-pKa supplies aqueous microstate free energies. When *pqr_text* is set,
    those G values are shifted by a Coulomb pocket term and Boltzmann-weighted
    again. Only microstates with aqueous population ≥ *min_aqueous_pct* (or the
    aqueous winner) are considered, so a 0.01% tautomer cannot win on noise.
    """
    from ..ionization.unipka_ensembles import g_effective, populations_from_states

    scored = ligand_ionization_ensemble(template, ensemble)
    pops = populations_from_states(scored, float(ph))
    if not pops:
        raise ValueError("Uni-pKa returned no protomers for the ligand at this pH.")
    aq_smi, aq_pct, aq_mol = pops[0]
    aq_by_smi = {smi: pct for smi, pct, _mol in pops}
    keys = set(ligand_keys or ())
    pqr_atoms = parse_pqr_atoms(pqr_text) if (pqr_text or "").strip() else []
    use_pocket = bool(pdb_block.strip()) and bool(pqr_atoms) and bool(keys)

    if not use_pocket:
        return LigandProtomerChoice(
            mol=Chem.Mol(aq_mol),
            smiles=str(aq_smi),
            charge=int(rdmolops.GetFormalCharge(aq_mol)),
            aqueous_pct=float(aq_pct),
            used_pocket=False,
        )

    keep_smi = {smi for smi, pct, _mol in pops if pct >= float(min_aqueous_pct)}
    keep_smi.add(aq_smi)
    pocket_rows: list[tuple[object, Chem.Mol, float, float]] = []
    for ms in getattr(scored, "microstates", ()):
        if ms.smiles not in keep_smi:
            continue
        protomer = Chem.MolFromSmiles(ms.smiles)
        if protomer is None:
            continue
        try:
            mapped = mol_from_ligand_pdb(pdb_block, template=protomer)
            mapped_h = Chem.AddHs(mapped, addCoords=True)
            Chem.SanitizeMol(mapped_h)
        except Exception:
            continue
        energy = ligand_pocket_coulomb_kcal(mapped_h, pqr_atoms, keys)
        g_pocket = float(ms.free_energy) + energy / _KT_KCAL
        pocket_rows.append((ms, mapped_h, energy, g_pocket))

    if not pocket_rows:
        return LigandProtomerChoice(
            mol=Chem.Mol(aq_mol),
            smiles=str(aq_smi),
            charge=int(rdmolops.GetFormalCharge(aq_mol)),
            aqueous_pct=float(aq_pct),
            used_pocket=False,
        )

    geffs = [
        g_effective(g_pocket, int(ms.charge), float(ph))
        for ms, _mapped, _energy, g_pocket in pocket_rows
    ]
    weights = _boltzmann_weights(geffs)
    acc: dict[str, float] = defaultdict(float)
    best: dict[str, tuple[Chem.Mol, float, int, float]] = {}
    for (ms, mapped, energy, _g), w in zip(pocket_rows, weights):
        smi = ms.smiles
        acc[smi] += w
        prev = best.get(smi)
        if prev is None or w > prev[3]:
            best[smi] = (mapped, energy, int(ms.charge), w)
    winner_smi = max(acc, key=acc.get)
    mapped, energy, charge, _w = best[winner_smi]
    return LigandProtomerChoice(
        mol=Chem.Mol(mapped),
        smiles=str(winner_smi),
        charge=int(charge),
        aqueous_pct=float(aq_by_smi.get(winner_smi, 0.0)),
        pocket_pct=100.0 * float(acc[winner_smi]),
        pocket_energy_kcal=float(energy),
        used_pocket=True,
    )


def _boltzmann_weights(geffs: list[float]) -> list[float]:
    if not geffs:
        return []
    m = min(geffs)
    raw = [math.exp(-(g - m)) for g in geffs]
    z = sum(raw)
    if z <= 0:
        n = len(raw)
        return [1.0 / n] * n
    return [w / z for w in raw]
