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

"""PDBQT/SDF docking I/O helpers used by Smina and the dock-results viewer.

Protein PDB cleanup stays in Tools → Dock → Prepare PDB. Protonation is not run here —
use Protonate / Fast Prepare first.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from rdkit import Chem

from .bundled_paths import resolve_user_executable
from .services.column_labels import COLUMN_PARENT_OID

logger = logging.getLogger(__name__)

_AFFINITY_RE = re.compile(
    r"REMARK\s+(?:minimizedAffinity\s+(-?[\d.]+)|VINA RESULT:\s+(-?[\d.]+))",
    re.IGNORECASE,
)
_POSE_STAGE_RE = re.compile(r"^REMARK\s+poseStage\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_SMILES_RE = re.compile(r"^REMARK\s+SMILES\s+(?!IDX)(\S.*)$", re.IGNORECASE | re.MULTILINE)
_SMILES_IDX_RE = re.compile(r"^REMARK\s+SMILES IDX\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_VINA_RESULT_LINE_RE = re.compile(
    r"^REMARK\s+VINA RESULT:\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)",
    re.IGNORECASE,
)
_NAME_REMARK_RE = re.compile(r"^REMARK\s+Name\s*=\s*(.+)$", re.IGNORECASE)
_SIMPLE_REMARK_RE = re.compile(r"^REMARK\s+([A-Za-z][A-Za-z0-9_]*)\s+(\S+)\s*$")
_MODE_HEADER_RE = re.compile(r"mode\s*\|\s*affinity", re.IGNORECASE)
_MODE_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$"
)
_SKIP_REMARK_KEYS = frozenset({"SMILES", "H", "ROOT", "BRANCH", "status", "between"})
DOCK_RESULT_PREFERRED_COLUMNS = (
    "SMILES",
    COLUMN_PARENT_OID,
    "mode",
    "minimizedAffinity",
    "minimizedRMSD",
    "rmsd_lb",
    "rmsd_ub",
    "poseStage",
    "Name",
)
OPENBABEL_LIGAND_SUFFIXES = {".sdf", ".sd", ".mol", ".mol2"}
SDF_POSE_SUFFIXES = {".sdf", ".sd"}
AUTOBOX_LIGAND_SUFFIXES = frozenset({".pdb", ".pdbqt"})
AUTOBOX_LIGAND_FILTER = "PDB / PDBQT (*.pdb *.pdbqt);;PDB (*.pdb);;PDBQT (*.pdbqt);;All files (*.*)"


def write_protein_setup(
    path: str | Path,
    *,
    center_x: float,
    center_y: float,
    center_z: float,
    size_x: float,
    size_y: float,
    size_z: float,
) -> Path:
    """Write a Vina/Smina ``--config`` grid file (center and size in Å)."""
    out = Path(path)
    out.write_text(
        (
            f"center_x = {float(center_x)}\n"
            f"center_y = {float(center_y)}\n"
            f"center_z = {float(center_z)}\n"
            f"size_x = {float(size_x)}\n"
            f"size_y = {float(size_y)}\n"
            f"size_z = {float(size_z)}\n"
        ),
        encoding="utf-8",
    )
    return out


def split_pdbqt_models(raw: str) -> list[str]:
    """Split a multi-MODEL PDBQT block into individual pose strings."""
    text = (raw or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    if re.search(r"^MODEL\b", text, re.MULTILINE):
        chunks = re.split(r"(?=^MODEL\b)", text, flags=re.MULTILINE)
        return [c.strip() + "\n" for c in chunks if c.strip()]
    return [text if text.endswith("\n") else text + "\n"]


def _strip_model_wrapper(block: str) -> str:
    """Remove MODEL/ENDMDL so a pose block can be used as a Smina ligand."""
    lines = [
        ln
        for ln in (block or "").splitlines(keepends=True)
        if not re.match(r"^(MODEL|ENDMDL)\b", ln)
    ]
    text = "".join(lines)
    return text if text.endswith("\n") else text + "\n"


def split_ligand_pdbqt_records(raw: str) -> list[str]:
    """Split a ligand PDBQT into one Meeko/Smina ligand per record.

    Smina/Vina parse a single ROOT…TORSDOF ligand. Concatenated conformers (a second
    ROOT after TORSDOF) raise ``Unknown or inappropriate tag``. MODEL/ENDMDL wrappers
    are also rejected as ligand input, so those tags are stripped from each record.
    """
    text = (raw or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    if re.search(r"^MODEL\b", text, re.MULTILINE):
        return [_strip_model_wrapper(c) for c in split_pdbqt_models(text)]
    if not re.search(r"^TORSDOF\b", text, re.MULTILINE):
        return [text if text.endswith("\n") else text + "\n"]
    records: list[str] = []
    buf: list[str] = []
    for line in text.splitlines(keepends=True):
        buf.append(line)
        if re.match(r"^TORSDOF\b", line):
            records.append("".join(buf))
            buf = []
    leftover = "".join(buf)
    if leftover.strip():
        records.append(leftover if leftover.endswith("\n") else leftover + "\n")
    return [r if r.endswith("\n") else r + "\n" for r in records if r.strip()]


def merge_pdbqt_files(paths: list[Path], dest: Path) -> None:
    """Concatenate PDBQT files (Smina pose outputs) into *dest*."""
    chunks: list[str] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if text and not text.endswith("\n"):
            text += "\n"
        chunks.append(text)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(chunks), encoding="utf-8")


def pose_stage_from_pdbqt(pdbqt: str) -> str | None:
    """``placement`` or ``minimized`` from a MolManager pose-stage remark."""
    match = _POSE_STAGE_RE.search(pdbqt or "")
    if match is None:
        return None
    return str(match.group(1)).strip() or None


def wrap_pdbqt_model(block: str, model_id: int, stage: str) -> str:
    """Wrap a ligand/pose block as ``MODEL`` with a ``poseStage`` remark."""
    body = _strip_model_wrapper(block)
    lines = [
        ln
        for ln in body.splitlines(keepends=True)
        if not re.match(r"^REMARK\s+poseStage\b", ln, re.I)
    ]
    body = "".join(lines)
    return f"MODEL {model_id}\nREMARK poseStage {stage}\n{body.rstrip()}\nENDMDL\n"


def combine_placement_and_minimized(placement_raw: str, minimized_blocks: list[str]) -> str:
    """Interleave placement poses with their energy-minimized counterparts."""
    places = split_pdbqt_models(placement_raw)
    chunks: list[str] = []
    model_id = 1
    for i, place in enumerate(places):
        chunks.append(wrap_pdbqt_model(place, model_id, "placement"))
        model_id += 1
        if i < len(minimized_blocks) and (minimized_blocks[i] or "").strip():
            chunks.append(wrap_pdbqt_model(minimized_blocks[i], model_id, "minimized"))
            model_id += 1
    return "".join(chunks)


def affinity_from_pdbqt(pdbqt: str) -> float | None:
    """Best-effort affinity (kcal/mol) from Smina/Vina PDBQT remarks."""
    match = _AFFINITY_RE.search(pdbqt or "")
    if match is None:
        return None
    raw = match.group(1) if match.group(1) is not None else match.group(2)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _fmt_score(raw: object) -> str:
    """Format a docking score or RMSD for a table cell."""
    try:
        return f"{float(raw):.3f}"
    except (TypeError, ValueError):
        return str(raw or "").strip()


def pose_metadata_from_pdbqt(pdbqt: str) -> dict[str, str]:
    """Extract Smina/Vina pose fields from PDBQT remarks (affinity, RMSD, name, …)."""
    meta: dict[str, str] = {}
    for line in (pdbqt or "").splitlines():
        text = line.strip()
        vina = _VINA_RESULT_LINE_RE.match(text)
        if vina:
            meta.setdefault("minimizedAffinity", _fmt_score(vina.group(1)))
            meta.setdefault("rmsd_lb", _fmt_score(vina.group(2)))
            meta.setdefault("rmsd_ub", _fmt_score(vina.group(3)))
            continue
        named = _NAME_REMARK_RE.match(text)
        if named:
            name = named.group(1).strip()
            if name:
                meta.setdefault("Name", name)
            continue
        smiles = _SMILES_RE.match(text)
        if smiles:
            smi = smiles.group(1).strip()
            if smi:
                meta.setdefault("SMILES", smi)
            continue
        simple = _SIMPLE_REMARK_RE.match(text)
        if simple is None:
            continue
        key, val = simple.group(1), simple.group(2)
        if key in _SKIP_REMARK_KEYS:
            continue
        if key.lower() == "minimizedrmsd" and val.strip() in {"-1", "-1.0"}:
            continue
        if key.lower() == "minimizedaffinity":
            meta.setdefault("minimizedAffinity", _fmt_score(val))
            continue
        meta.setdefault(key, val)
    score = affinity_from_pdbqt(pdbqt)
    if score is not None:
        meta.setdefault("minimizedAffinity", f"{score:.3f}")
    stage = pose_stage_from_pdbqt(pdbqt)
    if stage:
        meta.setdefault("poseStage", stage)
    return meta


def apply_pose_metadata(
    mol: Chem.Mol | None, meta: dict[str, str], *, overwrite: bool = False
) -> None:
    """Copy pose fields onto an RDKit molecule as SD properties."""
    if mol is None or not meta:
        return
    for key, value in meta.items():
        if not key or value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "Name":
            if overwrite or not (mol.HasProp("_Name") and mol.GetProp("_Name").strip()):
                mol.SetProp("_Name", text)
            if overwrite or not (mol.HasProp("Name") and mol.GetProp("Name").strip()):
                mol.SetProp("Name", text)
            continue
        if not overwrite and mol.HasProp(key) and mol.GetProp(key).strip():
            continue
        mol.SetProp(key, text)


def smina_log_pose_rows(log_text: str) -> list[dict[str, str]]:
    """Parse Smina/Vina mode tables (affinity, rmsd l.b., rmsd u.b.) from stdout/log."""
    rows: list[dict[str, str]] = []
    in_table = False
    for line in (log_text or "").splitlines():
        if _MODE_HEADER_RE.search(line):
            in_table = True
            continue
        if not in_table:
            continue
        stripped = line.strip()
        if not stripped or set(stripped) <= set("-+|"):
            continue
        match = _MODE_ROW_RE.match(line)
        if match is None:
            if stripped and not stripped.startswith("|"):
                in_table = False
            continue
        rows.append(
            {
                "mode": match.group(1),
                "minimizedAffinity": _fmt_score(match.group(2)),
                "rmsd_lb": _fmt_score(match.group(3)),
                "rmsd_ub": _fmt_score(match.group(4)),
            }
        )
    return rows


def merge_smina_log_into_poses(mols: list[Chem.Mol], log_text: str) -> None:
    """Attach mode-table fields to poses by index without overwriting existing SD data."""
    rows = smina_log_pose_rows(log_text)
    for mol, row in zip(mols, rows):
        apply_pose_metadata(mol, row, overwrite=False)


def pose_table_props(mol: Chem.Mol | None) -> dict[str, str]:
    """Public SD properties for one docked pose, including SMILES and Name."""
    out: dict[str, str] = {}
    if mol is None:
        return out
    if mol.HasProp("_Name"):
        name = mol.GetProp("_Name").strip()
        if name:
            out["Name"] = name
    for key in mol.GetPropNames():
        if not key or str(key).startswith("_"):
            continue
        try:
            val = (mol.GetProp(key) or "").strip()
        except Exception:
            val = ""
        if val:
            out[str(key)] = val
    if "SMILES" not in out:
        try:
            from .utils import mol_to_canonical_smiles

            smi = mol_to_canonical_smiles(mol)
        except Exception:
            smi = ""
        if smi:
            out["SMILES"] = smi
    return out


def dock_result_headers(mols: list[Chem.Mol]) -> list[str]:
    """Table headers for a dock-results window: structure plus all pose fields."""
    keys: set[str] = set()
    for mol in mols:
        keys.update(pose_table_props(mol).keys())
    tail: list[str] = []
    for name in DOCK_RESULT_PREFERRED_COLUMNS:
        if name in keys:
            tail.append(name)
            keys.discard(name)
    for name in sorted(keys):
        if name and name != "confs":
            tail.append(name)
    if "confs" not in tail:
        tail.append("confs")
    return ["ID_HIDDEN", "Structure"] + tail


def mols_from_pose_payloads(items: list) -> list[Chem.Mol]:
    """Rebuild pose molecules from ``(mol_blob, props)`` worker payloads."""
    mols: list[Chem.Mol] = []
    for item in items:
        if not item or len(item) < 2:
            continue
        blob, props = item[0], item[1]
        try:
            mol = Chem.Mol(bytes(blob)) if blob else None
        except Exception:
            mol = None
        if mol is None:
            continue
        apply_pose_metadata(mol, dict(props or {}), overwrite=True)
        mols.append(mol)
    return mols


def write_pose_mols_sdf(mols: list[Chem.Mol], path: str | Path) -> int:
    """Write pose molecules (with SD properties) to *path*. Returns records written."""
    from rdkit.Chem import SDWriter

    dest = Path(path)
    writer = SDWriter(str(dest))
    written = 0
    try:
        for mol in mols:
            if mol is None:
                continue
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    return written


def mols_from_dock_output(
    path: str | Path,
    *,
    template: Chem.Mol | None = None,
    log_text: str = "",
) -> list[Chem.Mol]:
    """Load docked poses from SDF or PDBQT and merge Smina log fields when present."""
    src = Path(path)
    if not src.is_file():
        return []
    if is_sdf_path(src):
        mols = load_sdf_mols(src)
    else:
        raw = src.read_text(encoding="utf-8", errors="replace")
        mols = []
        for i, block in enumerate(split_pdbqt_models(raw), start=1):
            mol = mol_from_pdbqt_block(block, template=template)
            if mol is None:
                continue
            if not (mol.HasProp("_Name") and mol.GetProp("_Name").strip()):
                mol.SetProp("_Name", f"{src.stem}_{i}")
            mols.append(mol)
    merge_smina_log_into_poses(mols, log_text)
    return mols


def sdf_path_for_pdbqt(pdbqt_path: str | Path) -> Path:
    """Sibling SDF path that shares the PDBQT stem (``out.pdbqt`` → ``out.sdf``)."""
    return Path(pdbqt_path).with_suffix(".sdf")


def ligand_is_openbabel_format(path: str | Path) -> bool:
    """True when Smina/OpenBabel can read bond orders from the ligand file."""
    return Path(path).suffix.lower() in OPENBABEL_LIGAND_SUFFIXES


def is_autobox_ligand_path(path: str | Path) -> bool:
    """True when *path* is a PDB or PDBQT file Smina can use for ``--autobox_ligand``."""
    return Path(path).suffix.lower() in AUTOBOX_LIGAND_SUFFIXES


def is_sdf_path(path: str | Path) -> bool:
    """True when *path* is an SDF pose/ligand file."""
    return Path(path).suffix.lower() in SDF_POSE_SUFFIXES


def load_sdf_mols(path: str | Path) -> list[Chem.Mol]:
    """Load molecules from an SDF, keeping explicit hydrogens."""
    from rdkit.Chem import SDMolSupplier

    src = Path(path)
    if not src.is_file():
        return []
    mols = [m for m in SDMolSupplier(str(src), removeHs=False) if m is not None]
    if mols:
        return mols
    return [m for m in SDMolSupplier(str(src), removeHs=False, sanitize=False) if m is not None]


def _pdbqt_atom_records(block: str) -> list[tuple[int, float, float, float]]:
    """Atomic number and coordinates for each ATOM/HETATM line, in file order."""
    from rdkit.Chem import GetPeriodicTable

    table = GetPeriodicTable()
    atoms: list[tuple[int, float, float, float]] = []
    for line in (block or "").splitlines():
        if not line.startswith(("ATOM", "HETATM")) or len(line) < 54:
            continue
        name = line[12:16].strip()
        letters = "".join(ch for ch in name if ch.isalpha())
        symbol = "H" if letters[:1].upper() == "H" else (letters[:1].upper() or "C")
        try:
            z = int(table.GetAtomicNumber(symbol))
        except Exception:
            z = 6
        try:
            x, y, zc = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        atoms.append((z, x, y, zc))
    return atoms


def _smiles_index_map(block: str) -> dict[int, int]:
    """0-based SMILES atom index → 0-based PDBQT ATOM index from Meeko remarks."""
    nums: list[int] = []
    for match in _SMILES_IDX_RE.finditer(block or ""):
        nums.extend(int(p) for p in match.group(1).split() if p.lstrip("-").isdigit())
    mapping: dict[int, int] = {}
    for i in range(0, len(nums) - 1, 2):
        mapping[nums[i] - 1] = nums[i + 1] - 1
    return mapping


def _apply_coords(mol: Chem.Mol, positions: list[tuple[float, float, float]]) -> Chem.Mol | None:
    n = int(mol.GetNumAtoms())
    if n != len(positions):
        return None
    out = Chem.Mol(mol)
    out.RemoveAllConformers()
    conf = Chem.Conformer(n)
    conf.Set3D(True)
    for i, (x, y, z) in enumerate(positions):
        conf.SetAtomPosition(i, (x, y, z))
    out.AddConformer(conf, assignId=True)
    try:
        Chem.SanitizeMol(out)
    except Exception:
        logger.debug("PDBQT pose sanitize failed", exc_info=True)
    return out


def _mol_from_pdbqt_smiles(block: str) -> Chem.Mol | None:
    """Rebuild connectivity from Meeko ``REMARK SMILES`` / ``SMILES IDX``."""
    match = _SMILES_RE.search(block or "")
    if match is None:
        return None
    mol = Chem.MolFromSmiles(match.group(1).strip())
    if mol is None:
        return None
    coords = _pdbqt_atom_records(block)
    idx_map = _smiles_index_map(block)
    n = int(mol.GetNumAtoms())
    if not coords or len(idx_map) < n:
        return None
    positions: list[tuple[float, float, float]] = []
    for smi_i in range(n):
        pdb_i = idx_map.get(smi_i)
        if pdb_i is None or pdb_i >= len(coords):
            return None
        _z, x, y, z = coords[pdb_i]
        positions.append((x, y, z))
    return _apply_coords(mol, positions)


def _mol_from_pdbqt_template(block: str, template: Chem.Mol) -> Chem.Mol | None:
    """Copy bond orders from *template* when heavy-atom identity/order matches."""
    heavy = [(z, x, y, zc) for z, x, y, zc in _pdbqt_atom_records(block) if z > 1]
    try:
        tmpl = Chem.RemoveHs(Chem.Mol(template), sanitize=False)
    except Exception:
        tmpl = Chem.Mol(template)
    if int(tmpl.GetNumAtoms()) != len(heavy):
        return None
    for i, atom in enumerate(tmpl.GetAtoms()):
        if int(atom.GetAtomicNum()) != heavy[i][0]:
            return None
    return _apply_coords(tmpl, [(x, y, zc) for _z, x, y, zc in heavy])


def _mol_from_pdbqt_proximity(block: str) -> Chem.Mol | None:
    """Guess bonds from PDB coordinates (no bond-order information in PDBQT)."""
    pdb_lines: list[str] = []
    for line in (block or "").splitlines():
        if line.startswith(("ATOM", "HETATM")):
            pdb_lines.append(line[:66].ljust(66))
        elif line.startswith(("MODEL", "ENDMDL", "TER", "CONECT", "END")):
            pdb_lines.append(line)
    if not any(ln.startswith(("ATOM", "HETATM")) for ln in pdb_lines):
        return None
    pdb_block = "\n".join(pdb_lines) + "\nEND\n"
    mol = Chem.MolFromPDBBlock(pdb_block, removeHs=False, sanitize=False)
    if mol is None:
        mol = Chem.MolFromPDBBlock(pdb_block, removeHs=True, sanitize=False)
    if mol is None:
        return None
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        logger.debug("PDBQT pose sanitize failed", exc_info=True)
    return mol


def mol_from_pdbqt_block(block: str, template: Chem.Mol | None = None) -> Chem.Mol | None:
    """Build an RDKit mol from a PDBQT pose, restoring bond orders when possible.

    PDBQT stores coordinates and AutoDock types, not Kekulé bond orders. Using
    PDB proximity bonding turns aromatics and double bonds into singles. Prefer
    Meeko ``REMARK SMILES`` mapping, then an optional input-molecule template.
    """
    mol = _mol_from_pdbqt_smiles(block)
    if mol is None and template is not None:
        mol = _mol_from_pdbqt_template(block, template)
    if mol is None:
        mol = _mol_from_pdbqt_proximity(block)
    if mol is not None:
        apply_pose_metadata(mol, pose_metadata_from_pdbqt(block))
    return mol


def write_pdbqt_poses_sdf(
    pdbqt_path: str | Path,
    sdf_path: str | Path | None = None,
    *,
    template: Chem.Mol | None = None,
) -> tuple[Path, int]:
    """Write each PDBQT MODEL as an SDF record.

    Default destination is the same stem as *pdbqt_path* with a ``.sdf`` suffix.
    Returns the SDF path and the number of records written. An empty conversion
    removes a leftover destination file.
    """
    from rdkit.Chem import SDWriter

    src = Path(pdbqt_path)
    dest = Path(sdf_path) if sdf_path is not None else sdf_path_for_pdbqt(src)
    raw = src.read_text(encoding="utf-8", errors="replace")
    writer = SDWriter(str(dest))
    written = 0
    try:
        for i, block in enumerate(split_pdbqt_models(raw), start=1):
            mol = mol_from_pdbqt_block(block, template=template)
            if mol is None:
                continue
            mol.SetProp("_Name", f"{src.stem}_{i}")
            apply_pose_metadata(mol, pose_metadata_from_pdbqt(block))
            stage = pose_stage_from_pdbqt(block)
            if stage:
                mol.SetProp("_Name", f"{src.stem}_{i}_{stage}")
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    if written == 0:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove empty SDF %s", dest, exc_info=True)
    return dest, written


def write_ligand_pdbqt_as_sdf(
    pdbqt_path: str | Path,
    sdf_path: str | Path,
    *,
    template: Chem.Mol | None = None,
) -> tuple[Path, int]:
    """Convert ligand PDBQT record(s) to SDF, restoring bond orders when possible."""
    from rdkit.Chem import SDWriter

    src = Path(pdbqt_path)
    dest = Path(sdf_path)
    raw = src.read_text(encoding="utf-8", errors="replace")
    records = split_ligand_pdbqt_records(raw)
    if not records:
        records = split_pdbqt_models(raw) or [raw]
    dest.parent.mkdir(parents=True, exist_ok=True)
    writer = SDWriter(str(dest))
    written = 0
    try:
        for i, block in enumerate(records, start=1):
            mol = mol_from_pdbqt_block(block, template=template)
            if mol is None:
                continue
            if not (mol.HasProp("_Name") and mol.GetProp("_Name").strip()):
                mol.SetProp("_Name", f"{src.stem}_{i}")
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    if written == 0:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            logger.debug("could not remove empty SDF %s", dest, exc_info=True)
    return dest, written


def _copy_sd_props(src: Chem.Mol, dest: Chem.Mol) -> None:
    if src.HasProp("_Name"):
        dest.SetProp("_Name", src.GetProp("_Name"))
    for key in src.GetPropNames():
        dest.SetProp(key, src.GetProp(key))


def _heavy_mol(mol: Chem.Mol) -> Chem.Mol:
    try:
        return Chem.RemoveHs(Chem.Mol(mol), sanitize=False)
    except Exception:
        return Chem.Mol(mol)


def _mol_from_pose_template(pose: Chem.Mol, template: Chem.Mol) -> Chem.Mol | None:
    """Copy docked coordinates onto *template* when heavy-atom identity/order matches."""
    if pose.GetNumConformers() < 1:
        return None
    pose_h = _heavy_mol(pose)
    tmpl = _heavy_mol(template)
    if int(pose_h.GetNumAtoms()) != int(tmpl.GetNumAtoms()):
        return None
    for i, atom in enumerate(tmpl.GetAtoms()):
        if int(atom.GetAtomicNum()) != int(pose_h.GetAtomWithIdx(i).GetAtomicNum()):
            return None
    conf = pose_h.GetConformer()
    positions = [
        (
            float(conf.GetAtomPosition(i).x),
            float(conf.GetAtomPosition(i).y),
            float(conf.GetAtomPosition(i).z),
        )
        for i in range(int(pose_h.GetNumAtoms()))
    ]
    out = _apply_coords(tmpl, positions)
    if out is None:
        return None
    _copy_sd_props(pose, out)
    return out


def restore_sdf_bond_orders(
    sdf_path: str | Path,
    templates: Chem.Mol | list[Chem.Mol] | None,
) -> int:
    """Rewrite an SDF so each pose uses template Kekulé/aromatic bonds.

    Docked coordinates are copied onto the first template whose heavy-atom
    identity and order match. Returns how many records were restored.
    """
    from rdkit.Chem import SDWriter

    src = Path(sdf_path)
    if templates is None:
        return 0
    if isinstance(templates, Chem.Mol):
        refs = [templates]
    else:
        refs = [m for m in templates if m is not None]
    if not refs:
        return 0
    poses = load_sdf_mols(src)
    if not poses:
        return 0
    restored: list[Chem.Mol] = []
    n_ok = 0
    for pose in poses:
        mapped = None
        for tmpl in refs:
            mapped = _mol_from_pose_template(pose, tmpl)
            if mapped is not None:
                break
        if mapped is not None:
            restored.append(mapped)
            n_ok += 1
        else:
            restored.append(pose)
    if n_ok == 0:
        return 0
    writer = SDWriter(str(src))
    try:
        for mol in restored:
            writer.write(mol)
    finally:
        writer.close()
    return n_ok


def combine_sdf_placement_and_minimized(
    placement_path: str | Path,
    minimized_path: str | Path,
    dest: str | Path | None = None,
) -> tuple[Path, int]:
    """Interleave placement and minimized SDF records with ``poseStage``."""
    from rdkit.Chem import SDWriter

    place_path = Path(placement_path)
    out = Path(dest) if dest is not None else place_path
    places = load_sdf_mols(place_path)
    mins = load_sdf_mols(minimized_path)
    writer = SDWriter(str(out))
    written = 0
    try:
        for i, place in enumerate(places, start=1):
            place.SetProp("poseStage", "placement")
            name = place.GetProp("_Name") if place.HasProp("_Name") else place_path.stem
            place.SetProp("_Name", f"{name}_{i}_placement")
            writer.write(place)
            written += 1
            if i - 1 < len(mins):
                minimized = mins[i - 1]
                minimized.SetProp("poseStage", "minimized")
                minimized.SetProp("_Name", f"{name}_{i}_minimized")
                writer.write(minimized)
                written += 1
    finally:
        writer.close()
    return out, written


def combine_pose_mols(pose_mols: list[Chem.Mol]) -> Chem.Mol | None:
    """Merge pose molecules that share the same atom count into one multi-conformer mol."""
    usable = [m for m in pose_mols if m is not None and int(m.GetNumConformers()) >= 1]
    if not usable:
        return None
    out = Chem.Mol(usable[0])
    n_atoms = int(out.GetNumAtoms())
    for extra in usable[1:]:
        if int(extra.GetNumAtoms()) != n_atoms:
            continue
        try:
            src = extra.GetConformer()
            conf = Chem.Conformer(n_atoms)
            for i in range(n_atoms):
                conf.SetAtomPosition(i, src.GetAtomPosition(i))
            conf.Set3D(True)
            out.AddConformer(conf, assignId=True)
        except Exception:
            logger.debug("skip pose conformer merge", exc_info=True)
    return out


def smina_executable_ok(path: str) -> bool:
    """True when *path* is an existing file or a name that might be on PATH."""
    return resolve_user_executable(path) is not None
