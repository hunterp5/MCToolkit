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


"""3D pharmacophore features, JSON files, RDKit BaseFeatures, and Gnina maps."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

FORMAT_ID = "molmanager.pharmacophore"
FORMAT_VERSION = 1
PHARMACOPHORE_FILE_FILTER = (
    "Pharmacophore (*.json *.mph4);;JSON (*.json);;MolManager pharmacophore (*.mph4);;"
    "All files (*.*)"
)

# RDKit BaseFeatures.fdef families, plus Exclusion (repulsive well for Gnina maps).
FEATURE_TYPES: tuple[tuple[str, str], ...] = (
    ("Donor", "H-bond donor"),
    ("Acceptor", "H-bond acceptor"),
    ("Aromatic", "Aromatic"),
    ("Hydrophobe", "Hydrophobe"),
    ("LumpedHydrophobe", "Lumped hydrophobe"),
    ("PosIonizable", "Positive ionizable"),
    ("NegIonizable", "Negative ionizable"),
    ("ZnBinder", "Zinc binder"),
    ("Exclusion", "Exclusion"),
)
FEATURE_TYPE_IDS: tuple[str, ...] = tuple(key for key, _label in FEATURE_TYPES)
_TYPE_LOOKUP = {key.lower(): key for key in FEATURE_TYPE_IDS}

# Empty string means any element. Common symbols for the editor combo.
FEATURE_ATOMS: tuple[tuple[str, str], ...] = (
    ("", "Any"),
    ("C", "C"),
    ("N", "N"),
    ("O", "O"),
    ("S", "S"),
    ("P", "P"),
    ("F", "F"),
    ("Cl", "Cl"),
    ("Br", "Br"),
    ("I", "I"),
    ("H", "H"),
    ("Zn", "Zn"),
)
_ATOM_ANY_ALIASES = {"", "*", "-", "any", "all"}

DEFAULT_RADIUS: dict[str, float] = {
    "Donor": 1.0,
    "Acceptor": 1.0,
    "Aromatic": 1.5,
    "Hydrophobe": 1.7,
    "LumpedHydrophobe": 2.0,
    "PosIonizable": 1.5,
    "NegIonizable": 1.5,
    "ZnBinder": 1.0,
    "Exclusion": 1.5,
}

FEATURE_COLORS: dict[str, str] = {
    "Donor": "#2ecc71",
    "Acceptor": "#e74c3c",
    "Aromatic": "#9b59b6",
    "Hydrophobe": "#f1c40f",
    "LumpedHydrophobe": "#d35400",
    "PosIonizable": "#3498db",
    "NegIonizable": "#e67e22",
    "ZnBinder": "#1abc9c",
    "Exclusion": "#7f8c8d",
}

_FACTORY = None


def normalize_feature_type(value: str, *, default: str = "Donor") -> str:
    """Map a user or RDKit family name onto a known feature type."""
    key = str(value or "").strip()
    if not key:
        return default
    return _TYPE_LOOKUP.get(key.lower(), default if key not in FEATURE_TYPE_IDS else key)


def default_feature_radius(feature_type: str) -> float:
    """Default sphere radius (Å) for a feature family."""
    return float(DEFAULT_RADIUS.get(normalize_feature_type(feature_type), 1.0))


def feature_color(feature_type: str) -> str:
    """Hex color used for the Protein Viewer overlay."""
    return FEATURE_COLORS.get(normalize_feature_type(feature_type), "#9b59b6")


def normalize_feature_atom(value: str) -> str:
    """Return a periodic-table symbol, or an empty string for any element."""
    raw = str(value or "").strip()
    if not raw or raw.lower() in _ATOM_ANY_ALIASES:
        return ""
    if raw.lower() in {"d", "t"}:
        return "H"
    if len(raw) == 1:
        return raw.upper()
    if len(raw) == 2:
        return raw[0].upper() + raw[1].lower()
    return ""


def feature_atom_matches(query_atom: str, ligand_atom: str) -> bool:
    """True when *query_atom* is Any or equals *ligand_atom*."""
    want = normalize_feature_atom(query_atom)
    if not want:
        return True
    return normalize_feature_atom(ligand_atom) == want


@dataclass
class PharmacophoreFeature:
    """One spherical pharmacophore site in Cartesian coordinates (Å)."""

    id: str
    type: str
    x: float
    y: float
    z: float
    radius: float = 1.0
    enabled: bool = True
    atom: str = ""

    def normalized(self) -> PharmacophoreFeature:
        """Return a copy with a known type, atom symbol, and a positive radius."""
        kind = normalize_feature_type(self.type)
        radius = float(self.radius)
        if not math.isfinite(radius) or radius <= 0.0:
            radius = default_feature_radius(kind)
        return replace(
            self,
            type=kind,
            atom=normalize_feature_atom(self.atom),
            radius=radius,
            enabled=bool(self.enabled),
        )

    def to_dict(self) -> dict[str, Any]:
        feat = self.normalized()
        return {
            "id": feat.id,
            "type": feat.type,
            "atom": feat.atom,
            "x": float(feat.x),
            "y": float(feat.y),
            "z": float(feat.z),
            "radius": float(feat.radius),
            "enabled": bool(feat.enabled),
        }

    def overlay_dict(self) -> dict[str, Any]:
        feat = self.normalized()
        payload = feat.to_dict()
        payload["color"] = feature_color(feat.type)
        return payload


@dataclass
class Pharmacophore:
    """Ordered list of 3D pharmacophore features."""

    features: list[PharmacophoreFeature] = field(default_factory=list)
    version: int = FORMAT_VERSION

    def enabled_features(self) -> list[PharmacophoreFeature]:
        return [feat.normalized() for feat in self.features if feat.enabled]

    def next_id(self) -> str:
        used = set()
        max_n = 0
        for feat in self.features:
            key = str(feat.id or "").strip()
            used.add(key)
            if key.startswith("f"):
                try:
                    max_n = max(max_n, int(key[1:]))
                except ValueError:
                    pass
        n = max_n + 1
        while f"f{n}" in used:
            n += 1
        return f"f{n}"

    def add_feature(
        self,
        *,
        feature_type: str,
        x: float,
        y: float,
        z: float,
        radius: float | None = None,
        enabled: bool = True,
        feature_id: str = "",
        atom: str = "",
    ) -> PharmacophoreFeature:
        kind = normalize_feature_type(feature_type)
        feat = PharmacophoreFeature(
            id=str(feature_id or "").strip() or self.next_id(),
            type=kind,
            x=float(x),
            y=float(y),
            z=float(z),
            radius=float(radius) if radius is not None else default_feature_radius(kind),
            enabled=bool(enabled),
            atom=atom,
        ).normalized()
        self.features.append(feat)
        return feat

    def replace_features(self, features: Iterable[PharmacophoreFeature]) -> None:
        self.features = [feat.normalized() for feat in features]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT_ID,
            "version": int(self.version or FORMAT_VERSION),
            "features": [feat.to_dict() for feat in self.features],
        }

    def overlay_payload(self) -> dict[str, Any]:
        enabled = [feat.overlay_dict() for feat in self.features if feat.enabled]
        return {"active": bool(enabled), "features": enabled}

    def bounding_box(
        self, *, padding: float = 0.0
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return (center, size) covering enabled features plus padding (Å)."""
        feats = self.enabled_features()
        if not feats:
            raise ValueError("Pharmacophore has no enabled features.")
        mins = [math.inf, math.inf, math.inf]
        maxs = [-math.inf, -math.inf, -math.inf]
        pad = max(0.0, float(padding))
        for feat in feats:
            extra = float(feat.radius) + pad
            coords = (feat.x, feat.y, feat.z)
            for i, value in enumerate(coords):
                mins[i] = min(mins[i], value - extra)
                maxs[i] = max(maxs[i], value + extra)
        center = tuple((lo + hi) * 0.5 for lo, hi in zip(mins, maxs))
        size = tuple(max(8.0, hi - lo) for lo, hi in zip(mins, maxs))
        return (center[0], center[1], center[2]), (size[0], size[1], size[2])


def pharmacophore_from_dict(raw: Any) -> Pharmacophore:
    """Parse a JSON object produced by :meth:`Pharmacophore.to_dict`."""
    if isinstance(raw, Pharmacophore):
        return raw
    if not isinstance(raw, dict):
        raise ValueError("Pharmacophore file must be a JSON object.")
    fmt = str(raw.get("format") or "").strip()
    if fmt and fmt != FORMAT_ID:
        raise ValueError(f"Unsupported pharmacophore format: {fmt}")
    try:
        version = int(raw.get("version") or FORMAT_VERSION)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pharmacophore version must be an integer.") from exc
    items = raw.get("features")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("Pharmacophore features must be a list.")
    features: list[PharmacophoreFeature] = []
    seen: set[str] = set()
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Pharmacophore feature {i} is not an object.")
        feat_id = str(item.get("id") or f"f{i}").strip() or f"f{i}"
        if feat_id in seen:
            feat_id = f"{feat_id}_{i}"
        seen.add(feat_id)
        try:
            x = float(item.get("x"))
            y = float(item.get("y"))
            z = float(item.get("z"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Pharmacophore feature {feat_id} needs numeric x, y, z.") from exc
        radius_raw = item.get("radius")
        kind = normalize_feature_type(str(item.get("type") or "Donor"))
        try:
            radius = float(radius_raw) if radius_raw is not None else default_feature_radius(kind)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Pharmacophore feature {feat_id} has a non-numeric radius.") from exc
        enabled = item.get("enabled", True)
        atom = item.get("atom")
        if atom is None:
            atom = item.get("elem") or item.get("element") or ""
        features.append(
            PharmacophoreFeature(
                id=feat_id,
                type=kind,
                x=x,
                y=y,
                z=z,
                radius=radius,
                enabled=bool(enabled),
                atom=str(atom or ""),
            ).normalized()
        )
    return Pharmacophore(features=features, version=version)


def load_pharmacophore(path: str | os.PathLike[str]) -> Pharmacophore:
    """Read a MolManager pharmacophore JSON file."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse pharmacophore JSON: {exc}") from exc
    return pharmacophore_from_dict(raw)


def save_pharmacophore(path: str | os.PathLike[str], pharmacophore: Pharmacophore) -> None:
    """Write a MolManager pharmacophore JSON file."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(pharmacophore.to_dict(), indent=2) + "\n", encoding="utf-8")


def feature_factory():
    """Cached RDKit ``MolChemicalFeatureFactory`` from BaseFeatures.fdef."""
    global _FACTORY
    if _FACTORY is None:
        from rdkit import RDConfig
        from rdkit.Chem import ChemicalFeatures

        fdef = os.path.join(RDConfig.RDDataDir, "BaseFeatures.fdef")
        _FACTORY = ChemicalFeatures.BuildFeatureFactory(fdef)
    return _FACTORY


def features_from_mol(mol, *, conf_id: int | None = None) -> list[PharmacophoreFeature]:
    """RDKit BaseFeatures sites for a molecule that already has a 3D conformer."""
    if mol is None or mol.GetNumAtoms() == 0:
        return []
    if mol.GetNumConformers() == 0:
        return []
    factory = feature_factory()
    target = mol
    if conf_id is not None:
        try:
            raw = factory.GetFeaturesForMol(mol, confId=int(conf_id))
        except TypeError:
            from rdkit import Chem

            target = Chem.Mol(mol)
            target.RemoveAllConformers()
            target.AddConformer(mol.GetConformer(int(conf_id)), assignId=True)
            raw = factory.GetFeaturesForMol(target)
    else:
        raw = factory.GetFeaturesForMol(target)
    out: list[PharmacophoreFeature] = []
    for i, feat in enumerate(raw, 1):
        family = normalize_feature_type(str(feat.GetFamily() or "Donor"))
        pos = feat.GetPos()
        out.append(
            PharmacophoreFeature(
                id=f"f{i}",
                type=family,
                x=float(pos.x),
                y=float(pos.y),
                z=float(pos.z),
                radius=default_feature_radius(family),
                atom=_feature_atom_from_rdkit(target, feat),
            )
        )
    return out


def _feature_atom_from_rdkit(mol, feat) -> str:
    """Element symbol when every RDKit site atom is the same element."""
    try:
        ids = list(feat.GetAtomIds() or ())
    except Exception:
        return ""
    symbols: set[str] = set()
    for idx in ids:
        try:
            sym = normalize_feature_atom(mol.GetAtomWithIdx(int(idx)).GetSymbol())
        except Exception:
            continue
        if sym:
            symbols.add(sym)
    heavies = {sym for sym in symbols if sym != "H"}
    pool = heavies or symbols
    if len(pool) == 1:
        return next(iter(pool))
    return ""


def ligand_pdb_from_atoms(atoms: Sequence[Any]) -> str:
    """Minimal HETATM PDB for RDKit from :class:`StructureAtom`-like records."""
    lines: list[str] = []
    for i, atom in enumerate(atoms, 1):
        name = str(getattr(atom, "name", "") or getattr(atom, "elem", "") or "C")[:4]
        resn = str(getattr(atom, "resn", "") or "LIG")[:3] or "LIG"
        chain = (str(getattr(atom, "chain", "") or " ")[:1] or " ").upper()
        resi_raw = str(getattr(atom, "resi", "") or "1").strip()
        try:
            resi = int(resi_raw.lstrip("+-") or "1")
            if resi_raw.startswith("-"):
                resi = -resi
        except ValueError:
            resi = 1
        elem = str(getattr(atom, "elem", "") or "C")[:2]
        x = float(getattr(atom, "x"))
        y = float(getattr(atom, "y"))
        z = float(getattr(atom, "z"))
        lines.append(
            f"HETATM{i:5d} {name:>4s} {resn:>3s} {chain}{resi:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {elem:>2s}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def mol_from_ligand_atoms(atoms: Sequence[Any]):
    """RDKit mol for ligand coordinates, or ``None`` if parsing fails."""
    pdb = ligand_pdb_from_atoms(atoms)
    if pdb.count("HETATM") == 0:
        return None
    try:
        from .workers.protein_prepare_ligand import mol_from_ligand_pdb

        return mol_from_ligand_pdb(pdb)
    except Exception:
        from rdkit import Chem

        try:
            mol = Chem.MolFromPDBBlock(pdb, removeHs=False, proximityBonding=True, sanitize=False)
        except TypeError:
            mol = Chem.MolFromPDBBlock(pdb, removeHs=False, sanitize=False)
        if mol is None or mol.GetNumAtoms() == 0:
            return None
        try:
            Chem.SanitizeMol(mol)
        except Exception:
            pass
        return mol


def _npts(size: float, spacing: float) -> int:
    n = int(round(float(size) / float(spacing)))
    if n < 2:
        n = 2
    if n % 2:
        n += 1
    return n


def write_autodock_map(
    path: str | os.PathLike[str],
    pharmacophore: Pharmacophore,
    *,
    center: Sequence[float],
    size: Sequence[float],
    spacing: float = 0.375,
    well_depth: float = 1.0,
) -> Path:
    """Write an AutoDock map of Gaussian wells for Gnina ``--user_grid``.

    Attractive families are negative wells; Exclusion is a positive (repulsive)
    well. Feature types are not encoded per atom type — Gnina's user grid is a
    single occupancy map.
    """
    feats = pharmacophore.enabled_features()
    if not feats:
        raise ValueError("Pharmacophore has no enabled features to map.")
    try:
        cx, cy, cz = (float(center[0]), float(center[1]), float(center[2]))
        sx, sy, sz = (float(size[0]), float(size[1]), float(size[2]))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("Pharmacophore map needs numeric box center and size.") from exc
    step = float(spacing)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("Pharmacophore map spacing must be positive.")
    nx, ny, nz = _npts(sx, step), _npts(sy, step), _npts(sz, step)
    depth = abs(float(well_depth)) or 1.0
    wells: list[tuple[float, float, float, float, float]] = []
    for feat in feats:
        sigma = max(0.25, float(feat.radius) / 2.0)
        amp = depth if feat.type == "Exclusion" else -depth
        wells.append((feat.x, feat.y, feat.z, sigma, amp))

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "GRID_PARAMETER_FILE none\n",
        "GRID_DATA_FILE none\n",
        "MACROMOLECULE none\n",
        f"SPACING {step:.3f}\n",
        f"NELEMENTS {nx} {ny} {nz}\n",
        f"CENTER {cx:.3f} {cy:.3f} {cz:.3f}\n",
    ]
    inv_two_sigma2 = [(0.5 / (sigma * sigma)) for *_xyz, sigma, _amp in wells]
    for iz in range(nz + 1):
        z = cz + (iz - nz / 2.0) * step
        for iy in range(ny + 1):
            y = cy + (iy - ny / 2.0) * step
            for ix in range(nx + 1):
                x = cx + (ix - nx / 2.0) * step
                energy = 0.0
                for (fx, fy, fz, _sigma, amp), k in zip(wells, inv_two_sigma2):
                    dx = x - fx
                    dy = y - fy
                    dz = z - fz
                    energy += amp * math.exp(-(dx * dx + dy * dy + dz * dz) * k)
                lines.append(f"{energy:.4f}\n")
    dest.write_text("".join(lines), encoding="ascii")
    return dest


def gnina_user_grid_paths(
    pharmacophore: Pharmacophore,
    *,
    out_path: str | os.PathLike[str],
    center: Sequence[float] | None = None,
    size: Sequence[float] | None = None,
    padding: float = 4.0,
) -> Path:
    """Write ``{out stem}_pharma.map`` covering the docking box or feature AABB."""
    if center is None or size is None:
        center, size = pharmacophore.bounding_box(padding=padding)
    dest = Path(out_path)
    map_path = dest.with_name(f"{dest.stem}_pharma.map")
    return write_autodock_map(map_path, pharmacophore, center=center, size=size)
