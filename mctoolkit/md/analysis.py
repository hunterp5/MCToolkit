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

"""Post-run MD trajectory analysis (RMSD, RMSF, energy / MM-GBSA join)."""

from __future__ import annotations

import csv
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..protein.structure_component_types import AMINO_ACIDS

_WATER_IONS = frozenset(
    {
        "HOH",
        "WAT",
        "TIP",
        "TIP3",
        "T3P",
        "SOL",
        "NA",
        "CL",
        "NA+",
        "CL-",
        "SOD",
        "CLA",
        "K",
        "K+",
        "MG",
        "CA",
    }
)
_SIDECAR_VERSION = 1


@dataclass(frozen=True)
class TrajectoryAtom:
    """One ATOM/HETATM row from a DCD-matching topology PDB."""

    index: int
    name: str
    resn: str
    chain: str
    resi: str
    icode: str
    element: str


@dataclass(frozen=True)
class ResidueRmsf:
    chain: str
    resi: str
    icode: str
    resn: str
    rmsf: float


@dataclass
class TrajectoryAnalysis:
    """Per-frame series plus per-residue CA RMSF (Å)."""

    time_ps: np.ndarray
    protein_ca_rmsd: np.ndarray
    ligand_rmsd: np.ndarray
    ligand_com_drift: np.ndarray
    e_pot: np.ndarray
    dg: np.ndarray
    rmsf: list[ResidueRmsf] = field(default_factory=list)
    n_frames: int = 0
    n_atoms: int = 0
    n_solute: int = 0
    summary: str = ""


def sidecar_path_for_dcd(dcd_path: str | Path) -> Path:
    rec = Path(dcd_path)
    return Path(str(rec) + ".json")


def write_run_sidecar(
    dcd_path: str | Path,
    *,
    topology: str,
    last_frame: str = "",
    energy_csv: str = "",
    mmgbsa_csv: str = "",
    timestep_fs: float = 2.0,
    dcd_interval_steps: int = 0,
    solute_atoms: int = 0,
    ligand_keys: list[tuple[str, str, str]] | tuple = (),
    wrap_dcd: bool = False,
) -> Path:
    """Describe one production DCD for Analyze Trajectory."""
    rec = sidecar_path_for_dcd(dcd_path)
    rec.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _SIDECAR_VERSION,
        "dcd": str(Path(dcd_path)),
        "topology": topology,
        "last_frame": last_frame,
        "energy_csv": energy_csv,
        "mmgbsa_csv": mmgbsa_csv,
        "timestep_fs": float(timestep_fs),
        "dcd_interval_steps": int(dcd_interval_steps),
        "solute_atoms": int(solute_atoms),
        "ligand_keys": [list(key) for key in ligand_keys],
        "wrap_dcd": bool(wrap_dcd),
    }
    rec.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return rec


def read_run_sidecar(path: str | Path) -> dict:
    rec = Path(path)
    if rec.suffix.lower() == ".dcd":
        rec = sidecar_path_for_dcd(rec)
    if not rec.is_file():
        return {}
    try:
        payload = json.loads(rec.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_pdb_atoms(text: str) -> list[TrajectoryAtom]:
    """ATOM/HETATM records in file order (must match DCD atom order)."""
    atoms: list[TrajectoryAtom] = []
    for line in text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        padded = f"{line:<80}"
        name = padded[12:16].strip()
        resn = padded[17:20].strip().upper()
        chain = padded[21:22].strip()
        resi = padded[22:26].strip()
        icode = padded[26:27].strip()
        element = padded[76:78].strip() or (name[:1] if name else "")
        atoms.append(
            TrajectoryAtom(
                index=len(atoms),
                name=name,
                resn=resn,
                chain=chain,
                resi=resi,
                icode=icode,
                element=element.upper(),
            )
        )
    return atoms


def read_dcd_xyz(path: str | Path) -> np.ndarray:
    """Read an OpenMM/CHARMM little-endian DCD into Å (n_frames, n_atoms, 3)."""
    rec = Path(path)
    data = rec.read_bytes()
    if len(data) < 276:
        raise RuntimeError(f"DCD header is truncated: {rec}")
    endian = "<" if struct.unpack_from("<i", data, 0)[0] == 84 else ">"
    if data[4:8] != b"CORD":
        raise RuntimeError(f"Not a CORD DCD: {rec}")
    box_flag = struct.unpack_from(endian + "i", data, 48)[0]
    n_atoms = struct.unpack_from(endian + "i", data, 268)[0]
    if n_atoms <= 0:
        raise RuntimeError(f"DCD atom count is invalid: {rec}")
    off = 276
    rec_xyz = 8 + 4 * n_atoms
    frames: list[np.ndarray] = []
    dtype = np.dtype(endian + "f4")
    while off + 3 * rec_xyz <= len(data):
        if box_flag:
            if off + 56 > len(data):
                break
            off += 56
            if off + 3 * rec_xyz > len(data):
                break
        cols = []
        for _ in range(3):
            cols.append(np.frombuffer(data, dtype=dtype, count=n_atoms, offset=off + 4))
            off += rec_xyz
        frames.append(np.column_stack(cols).astype(float))
    if not frames:
        raise RuntimeError(f"DCD has no frames: {rec}")
    return np.stack(frames, axis=0)


def kabsch_rotation(
    mobile: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (R, mobile_com, target_com) so (mobile - mc) @ R + tc ~= target."""
    p = np.asarray(mobile, dtype=float)
    q = np.asarray(target, dtype=float)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3 or p.shape[0] == 0:
        raise ValueError("Kabsch needs matching Nx3 coordinates.")
    mc = p.mean(axis=0)
    tc = q.mean(axis=0)
    if p.shape[0] == 1:
        return np.eye(3), mc, tc
    pc = p - mc
    qc = q - tc
    u, _s, vt = np.linalg.svd(pc.T @ qc)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0.0:
        vt[-1, :] *= -1.0
        rot = vt.T @ u.T
    return rot, mc, tc


def apply_kabsch(
    xyz: np.ndarray, rot: np.ndarray, mobile_com: np.ndarray, target_com: np.ndarray
) -> np.ndarray:
    return (xyz - mobile_com) @ rot + target_com


def _rmsd(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    n = diff.shape[0]
    if n <= 0:
        return float("nan")
    return float(np.sqrt(float((diff * diff).sum()) / n))


def _atom_key(atom: TrajectoryAtom) -> tuple[str, str, str]:
    return (atom.chain, atom.resi, atom.icode)


def select_indices(
    atoms: list[TrajectoryAtom],
    *,
    ligand_keys: set[tuple[str, str, str]] | None = None,
) -> tuple[list[int], list[int], dict[tuple[str, str, str, str], list[int]]]:
    """Protein CA indices, ligand heavy-atom indices, CA indices by residue."""
    lig = ligand_keys or set()
    ca: list[int] = []
    ligand_heavy: list[int] = []
    ca_by_res: dict[tuple[str, str, str, str], list[int]] = {}
    for atom in atoms:
        resn = atom.resn.upper()
        key = _atom_key(atom)
        is_water = resn in _WATER_IONS
        if lig:
            is_lig = key in lig
        else:
            is_lig = (not is_water) and resn not in AMINO_ACIDS
        is_protein = (not is_lig) and (not is_water) and resn in AMINO_ACIDS
        element = (atom.element or atom.name[:1] or "").upper()
        if is_protein and atom.name == "CA":
            ca.append(atom.index)
            ca_by_res.setdefault((atom.chain, atom.resi, atom.icode, atom.resn), []).append(
                atom.index
            )
        if is_lig and element != "H":
            ligand_heavy.append(atom.index)
    return ca, ligand_heavy, ca_by_res


def dcd_times_ps(n_frames: int, *, timestep_fs: float, interval_steps: int) -> np.ndarray:
    dt_ps = float(timestep_fs) / 1000.0
    step = max(1, int(interval_steps))
    return np.asarray([(i + 1) * step * dt_ps for i in range(int(n_frames))], dtype=float)


def _nearest_values(times: np.ndarray, series_t: np.ndarray, series_v: np.ndarray) -> np.ndarray:
    out = np.full(times.shape, np.nan, dtype=float)
    if series_t.size == 0:
        return out
    for i, t in enumerate(times):
        j = int(np.argmin(np.abs(series_t - t)))
        out[i] = float(series_v[j])
    return out


def read_xy_csv(path: str | Path, x_field: str, y_field: str) -> tuple[np.ndarray, np.ndarray]:
    rec = Path(path)
    if not rec.is_file():
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    xs: list[float] = []
    ys: list[float] = []
    with rec.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                xs.append(float(row[x_field]))
                ys.append(float(row[y_field]))
            except (KeyError, TypeError, ValueError):
                continue
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def analyze_xyz(
    xyz: np.ndarray,
    atoms: list[TrajectoryAtom],
    *,
    time_ps: np.ndarray | None = None,
    solute_atoms: int = 0,
    ligand_keys: set[tuple[str, str, str]] | None = None,
    energy_t: np.ndarray | None = None,
    energy_v: np.ndarray | None = None,
    dg_t: np.ndarray | None = None,
    dg_v: np.ndarray | None = None,
) -> TrajectoryAnalysis:
    """CA-fit RMSD / ligand RMSD / RMSF on a coordinate stack in Å."""
    coords = np.asarray(xyz, dtype=float)
    if coords.ndim != 3 or coords.shape[-1] != 3:
        raise RuntimeError("Trajectory must be (n_frames, n_atoms, 3).")
    n_frames, n_atoms, _ = coords.shape
    n_sol = int(solute_atoms)
    if n_sol > 0:
        if n_sol > n_atoms:
            raise RuntimeError(f"Solute atom count {n_sol} exceeds DCD ({n_atoms} atoms).")
        coords = coords[:, :n_sol, :]
        atoms = atoms[:n_sol]
        n_atoms = n_sol
    if len(atoms) != n_atoms:
        raise RuntimeError(f"Topology has {len(atoms)} atoms but the trajectory has {n_atoms}.")
    times = (
        np.asarray(time_ps, dtype=float)
        if time_ps is not None
        else np.arange(n_frames, dtype=float)
    )
    if times.shape[0] != n_frames:
        times = np.arange(n_frames, dtype=float)
    ca_idx, lig_idx, ca_by_res = select_indices(atoms, ligand_keys=ligand_keys)
    prot = np.full(n_frames, np.nan)
    lig_rmsd = np.full(n_frames, np.nan)
    com_drift = np.full(n_frames, np.nan)
    fitted = coords.copy()
    if ca_idx:
        ref_ca = coords[0, ca_idx, :]
        for i in range(n_frames):
            rot, mc, tc = kabsch_rotation(coords[i, ca_idx, :], ref_ca)
            fitted[i] = apply_kabsch(coords[i], rot, mc, tc)
            prot[i] = _rmsd(fitted[i, ca_idx, :], ref_ca)
            if lig_idx:
                lig_rmsd[i] = _rmsd(fitted[i, lig_idx, :], fitted[0, lig_idx, :])
                com_i = fitted[i, lig_idx, :].mean(axis=0)
                com_0 = fitted[0, lig_idx, :].mean(axis=0)
                com_drift[i] = float(np.linalg.norm(com_i - com_0))
        prot[0] = 0.0
        if lig_idx:
            lig_rmsd[0] = 0.0
            com_drift[0] = 0.0
    elif lig_idx:
        ref_lig = coords[0, lig_idx, :]
        for i in range(n_frames):
            lig_rmsd[i] = _rmsd(coords[i, lig_idx, :], ref_lig)
            com_i = coords[i, lig_idx, :].mean(axis=0)
            com_0 = ref_lig.mean(axis=0)
            com_drift[i] = float(np.linalg.norm(com_i - com_0))
        lig_rmsd[0] = 0.0
        com_drift[0] = 0.0
    rmsf_rows: list[ResidueRmsf] = []
    if ca_idx and n_frames > 1:
        for (chain, resi, icode, resn), idxs in ca_by_res.items():
            pos = fitted[:, idxs[0], :]
            rmsf = float(np.sqrt(np.mean(np.sum((pos - pos.mean(axis=0)) ** 2, axis=1))))
            rmsf_rows.append(ResidueRmsf(chain=chain, resi=resi, icode=icode, resn=resn, rmsf=rmsf))
    e_pot = np.full(n_frames, np.nan)
    dg = np.full(n_frames, np.nan)
    if energy_t is not None and energy_v is not None:
        e_pot = _nearest_values(times, energy_t, energy_v)
    if dg_t is not None and dg_v is not None:
        dg = _nearest_values(times, dg_t, dg_v)
    summary = _format_summary(times, prot, lig_rmsd, com_drift, dg, n_frames)
    return TrajectoryAnalysis(
        time_ps=times,
        protein_ca_rmsd=prot,
        ligand_rmsd=lig_rmsd,
        ligand_com_drift=com_drift,
        e_pot=e_pot,
        dg=dg,
        rmsf=rmsf_rows,
        n_frames=n_frames,
        n_atoms=n_atoms,
        n_solute=n_atoms,
        summary=summary,
    )


def _finite_stats(values: np.ndarray) -> tuple[float | None, float | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None
    return float(finite.mean()), float(finite.max())


def _format_summary(
    times: np.ndarray,
    prot: np.ndarray,
    lig: np.ndarray,
    drift: np.ndarray,
    dg: np.ndarray,
    n_frames: int,
) -> str:
    lines = [f"Frames: {n_frames}"]
    if times.size:
        lines.append(f"Time: {float(times[0]):.2f}–{float(times[-1]):.2f} ps")
    mean, peak = _finite_stats(prot)
    if mean is not None:
        lines.append(f"Protein Cα RMSD: mean {mean:.2f} Å  max {peak:.2f} Å")
    mean, peak = _finite_stats(lig)
    if mean is not None:
        lines.append(f"Ligand RMSD (after Cα fit): mean {mean:.2f} Å  max {peak:.2f} Å")
    mean, peak = _finite_stats(drift)
    if mean is not None:
        lines.append(f"Ligand COM drift: mean {mean:.2f} Å  max {peak:.2f} Å")
    mean, peak = _finite_stats(dg)
    if mean is not None:
        lines.append(f"MM-GBSA ΔG: mean {mean:.2f} kcal/mol  max {peak:.2f} kcal/mol")
    lines.append("Cα-fitted to frame 0. Not a DCD player.")
    return "\n".join(lines) + "\n"


def write_analysis_csv(path: Path, result: TrajectoryAnalysis) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "frame",
        "time_ps",
        "protein_ca_rmsd",
        "ligand_rmsd",
        "ligand_com_drift",
        "E_pot_kcal",
        "dG",
    )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i in range(result.n_frames):
            writer.writerow(
                {
                    "frame": i,
                    "time_ps": f"{float(result.time_ps[i]):.4f}",
                    "protein_ca_rmsd": _csv_num(result.protein_ca_rmsd[i]),
                    "ligand_rmsd": _csv_num(result.ligand_rmsd[i]),
                    "ligand_com_drift": _csv_num(result.ligand_com_drift[i]),
                    "E_pot_kcal": _csv_num(result.e_pot[i]),
                    "dG": _csv_num(result.dg[i]),
                }
            )


def write_rmsf_csv(path: Path, result: TrajectoryAnalysis) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=("chain", "resi", "icode", "resn", "rmsf"))
        writer.writeheader()
        for row in result.rmsf:
            writer.writerow(
                {
                    "chain": row.chain,
                    "resi": row.resi,
                    "icode": row.icode,
                    "resn": row.resn,
                    "rmsf": f"{row.rmsf:.6f}",
                }
            )


def _csv_num(value: float) -> str:
    if value is None or not np.isfinite(value):
        return ""
    return f"{float(value):.6f}"


def write_pdb_frame(path: Path, atoms: list[TrajectoryAtom], xyz: np.ndarray) -> Path:
    """Write solute coordinates (Å) as PDB for Protein Viewer overlay."""
    lines = ["REMARK   4 MCTK MD ANALYSIS FRAME"]
    for atom, pos in zip(atoms, xyz, strict=True):
        x, y, z = (float(pos[0]), float(pos[1]), float(pos[2]))
        rec = "HETATM" if atom.resn not in AMINO_ACIDS else "ATOM  "
        name = atom.name[:4]
        chain = (atom.chain or " ")[:1]
        try:
            resi = int(atom.resi or 0)
        except ValueError:
            resi = 0
        icode = (atom.icode or " ")[:1]
        lines.append(
            f"{rec}{atom.index + 1:5d} {name:>4s} {atom.resn:>3s} {chain}"
            f"{resi:4d}{icode}   "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {atom.element:>2s}"
        )
    lines.append("END")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def analyze_trajectory(
    *,
    dcd_path: str,
    topology_path: str,
    sidecar_path: str = "",
    energy_csv: str = "",
    mmgbsa_csv: str = "",
    solute_atoms: int = 0,
    timestep_fs: float = 2.0,
    dcd_interval_steps: int = 0,
    ligand_keys: set[tuple[str, str, str]] | None = None,
) -> TrajectoryAnalysis:
    """Load DCD + topology PDB and compute v1 analysis series."""
    meta = read_run_sidecar(sidecar_path) if sidecar_path else {}
    if not meta and dcd_path:
        meta = read_run_sidecar(dcd_path)
    topology = topology_path or str(meta.get("topology") or "")
    if not topology:
        raise RuntimeError("Analyze Trajectory needs a topology PDB that matches the DCD.")
    top_path = Path(topology)
    if not top_path.is_file():
        raise RuntimeError(f"Topology not found: {top_path}")
    dcd = Path(dcd_path)
    if not dcd.is_file():
        raise RuntimeError(f"DCD not found: {dcd}")
    atoms = parse_pdb_atoms(top_path.read_text(encoding="utf-8", errors="replace"))
    if not atoms:
        raise RuntimeError("Topology PDB has no ATOM/HETATM records.")
    xyz = read_dcd_xyz(dcd)
    n_sol = int(solute_atoms or meta.get("solute_atoms") or 0)
    dt = float(timestep_fs or meta.get("timestep_fs") or 2.0)
    interval = int(dcd_interval_steps or meta.get("dcd_interval_steps") or 0)
    times = dcd_times_ps(xyz.shape[0], timestep_fs=dt, interval_steps=interval or 1)
    keys = ligand_keys
    if keys is None:
        raw = meta.get("ligand_keys") or []
        keys = {
            (str(item[0]), str(item[1]), str(item[2]))
            for item in raw
            if isinstance(item, (list, tuple)) and len(item) >= 3
        }
    energy_path = energy_csv or str(meta.get("energy_csv") or "")
    mmgbsa_path = mmgbsa_csv or str(meta.get("mmgbsa_csv") or "")
    e_t, e_v = read_xy_csv(energy_path, "time_ps", "E_pot_kcal") if energy_path else (None, None)
    g_t, g_v = read_xy_csv(mmgbsa_path, "time_ps", "dG") if mmgbsa_path else (None, None)
    return analyze_xyz(
        xyz,
        atoms,
        time_ps=times,
        solute_atoms=n_sol,
        ligand_keys=keys,
        energy_t=e_t,
        energy_v=e_v,
        dg_t=g_t,
        dg_v=g_v,
    )


def extract_frame_pdb(
    *,
    dcd_path: str,
    topology_path: str,
    frame: int,
    dest: str | Path,
    solute_atoms: int = 0,
    sidecar_path: str = "",
) -> Path:
    """Write one solute frame as PDB for overlay (not playback)."""
    meta = read_run_sidecar(sidecar_path) if sidecar_path else read_run_sidecar(dcd_path)
    top = topology_path or str(meta.get("topology") or "")
    atoms = parse_pdb_atoms(Path(top).read_text(encoding="utf-8", errors="replace"))
    xyz = read_dcd_xyz(dcd_path)
    n_sol = int(solute_atoms or meta.get("solute_atoms") or 0)
    if n_sol > 0:
        xyz = xyz[:, :n_sol, :]
        atoms = atoms[:n_sol]
    idx = int(frame)
    if idx < 0 or idx >= xyz.shape[0]:
        raise RuntimeError(f"Frame {idx} is outside 0…{xyz.shape[0] - 1}.")
    return write_pdb_frame(Path(dest), atoms, xyz[idx])
