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

"""1-trajectory MM-GBSA energy terms from OpenMM implicit-solvent systems."""

from __future__ import annotations

import csv
import logging
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..platform_support.exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)

_BONDED_FORCE_NAMES = frozenset(
    {
        "HarmonicBondForce",
        "HarmonicAngleForce",
        "PeriodicTorsionForce",
        "RBTorsionForce",
        "CMAPTorsionForce",
        "CustomTorsionForce",
        "CustomAngleForce",
    }
)
_GROUP_BONDED = 0
_GROUP_NONBONDED = 1
_GROUP_GB = 2
_GROUP_SA = 3
_GROUP_OTHER = 4


@dataclass(frozen=True)
class MMGBSATerms:
    """Potential energy pieces in kcal/mol (vacuum MM + GBSA)."""

    total: float
    bonded: float = 0.0
    vdw: float = 0.0
    elec: float = 0.0
    gb: float = 0.0
    sa: float = 0.0
    other: float = 0.0

    @property
    def ggas(self) -> float:
        """Gas-phase MM (bonded + vdW + elec)."""
        return self.bonded + self.vdw + self.elec

    @property
    def gsolv(self) -> float:
        """Polar + nonpolar solvation (GB + SA)."""
        return self.gb + self.sa


@dataclass(frozen=True)
class MMGBSAResult:
    """Complex / receptor / ligand terms and 1-trajectory deltas (kcal/mol)."""

    complex: MMGBSATerms
    receptor: MMGBSATerms
    ligand: MMGBSATerms
    time_ps: float | None = None
    frame: int | None = None
    solvent: str = "gbn2"
    salt_m: float = 0.15
    protein_ff: str = ""
    ligand_ff: str = ""
    charge_tag: str = ""
    note: str = ""

    @property
    def delta(self) -> MMGBSATerms:
        return delta_terms(self.complex, self.receptor, self.ligand)


def delta_terms(complex_e: MMGBSATerms, receptor: MMGBSATerms, ligand: MMGBSATerms) -> MMGBSATerms:
    """Δ = E_complex − E_receptor − E_ligand."""
    return MMGBSATerms(
        total=complex_e.total - receptor.total - ligand.total,
        bonded=complex_e.bonded - receptor.bonded - ligand.bonded,
        vdw=complex_e.vdw - receptor.vdw - ligand.vdw,
        elec=complex_e.elec - receptor.elec - ligand.elec,
        gb=complex_e.gb - receptor.gb - ligand.gb,
        sa=complex_e.sa - receptor.sa - ligand.sa,
        other=complex_e.other - receptor.other - ligand.other,
    )


def force_kind(force: object) -> str:
    """Classify an OpenMM Force as bonded, nonbonded, gb, sa, or other."""
    name = type(force).__name__
    if name in _BONDED_FORCE_NAMES or name.endswith("TorsionForce"):
        return "bonded"
    if name == "CustomBondForce" and "harmonic" in _force_energy_text(force):
        return "bonded"
    if name == "NonbondedForce":
        return "nonbonded"
    if name in {"CustomGBForce", "GBSAOBCForce", "GBnForce"}:
        return "gb"
    if "GBSA" in name or "SurfaceArea" in name:
        return "sa"
    expr = _force_energy_text(force)
    compact = expr.replace(" ", "").replace("_", "")
    if "surfacearea" in compact or "surfacearea" in expr:
        return "sa"
    if "bornradi" in compact or "igb" in expr or "gb" in compact:
        return "gb"
    return "other"


def _force_energy_text(force: object) -> str:
    for attr in ("getEnergyFunction", "getEnergyExpression"):
        getter = getattr(force, attr, None)
        if callable(getter):
            try:
                return str(getter() or "").lower()
            except Exception:  # noqa: BLE001
                log_swallowed_exception(logger, f"force energy expression ({attr})")
                return ""
    return ""


def assign_force_groups(system) -> None:
    """Put bonded / nonbonded / GB / SA into distinct OpenMM force groups."""
    for force in system.getForces():
        kind = force_kind(force)
        if kind == "bonded":
            force.setForceGroup(_GROUP_BONDED)
        elif kind == "nonbonded":
            force.setForceGroup(_GROUP_NONBONDED)
        elif kind == "gb":
            force.setForceGroup(_GROUP_GB)
        elif kind == "sa":
            force.setForceGroup(_GROUP_SA)
        else:
            force.setForceGroup(_GROUP_OTHER)


def _kcal(energy) -> float:
    from openmm import unit

    return float(energy.value_in_unit(unit.kilocalories_per_mole))


def _group_energy(context, group: int) -> float:
    state = context.getState(getEnergy=True, groups={group})
    return _kcal(state.getPotentialEnergy())


def _split_nonbonded(context, system) -> tuple[float, float]:
    """Return (vdw, elec) for NonbondedForce by zeroing charges in-context."""
    from openmm import NonbondedForce

    combined = _group_energy(context, _GROUP_NONBONDED)
    nb = None
    for force in system.getForces():
        if isinstance(force, NonbondedForce):
            nb = force
            break
    if nb is None:
        return 0.0, combined
    saved: list[tuple[object, object, object]] = []
    for i in range(nb.getNumParticles()):
        saved.append(nb.getParticleParameters(i))
    exceptions: list[tuple[int, int, object, object, object]] = []
    for i in range(nb.getNumExceptions()):
        p1, p2, q, sig, eps = nb.getExceptionParameters(i)
        exceptions.append((p1, p2, q, sig, eps))
    try:
        zero = saved[0][0] * 0 if saved else 0.0
        for i, (_q, sig, eps) in enumerate(saved):
            nb.setParticleParameters(i, zero, sig, eps)
        for p1, p2, _q, sig, eps in exceptions:
            nb.setExceptionParameters(p1, p2, zero, sig, eps)
        nb.updateParametersInContext(context)
        vdw = _group_energy(context, _GROUP_NONBONDED)
    finally:
        for i, (q, sig, eps) in enumerate(saved):
            nb.setParticleParameters(i, q, sig, eps)
        for p1, p2, q, sig, eps in exceptions:
            nb.setExceptionParameters(p1, p2, q, sig, eps)
        nb.updateParametersInContext(context)
    return vdw, combined - vdw


def terms_from_context(context, system) -> MMGBSATerms:
    """Evaluate grouped energies on an existing OpenMM Context."""
    total = _kcal(context.getState(getEnergy=True).getPotentialEnergy())
    bonded = _group_energy(context, _GROUP_BONDED)
    gb = _group_energy(context, _GROUP_GB)
    sa = _group_energy(context, _GROUP_SA)
    other = _group_energy(context, _GROUP_OTHER)
    try:
        vdw, elec = _split_nonbonded(context, system)
    except Exception:  # noqa: BLE001
        log_swallowed_exception(logger, "MM-GBSA nonbonded split")
        combined = _group_energy(context, _GROUP_NONBONDED)
        vdw, elec = 0.0, combined
    return MMGBSATerms(
        total=total,
        bonded=bonded,
        vdw=vdw,
        elec=elec,
        gb=gb,
        sa=sa,
        other=other,
    )


def _verlet_simulation(topology, system, positions, create_simulation: Callable):
    from openmm import VerletIntegrator, unit

    integrator = VerletIntegrator(0.001 * unit.picoseconds)
    simulation = create_simulation(topology, system, integrator)
    simulation.context.setPositions(positions)
    return simulation


def score_system_terms(
    topology,
    system,
    positions,
    create_simulation: Callable,
) -> MMGBSATerms:
    """Single-point MM-GBSA terms for one topology (complex, receptor, or ligand)."""
    assign_force_groups(system)
    simulation = _verlet_simulation(topology, system, positions, create_simulation)
    try:
        return terms_from_context(simulation.context, system)
    finally:
        del simulation


def slice_complex_positions(complex_positions, n_receptor: int):
    """Split tleap ``combine { PROT LIG }`` coordinates into receptor then ligand."""
    n = len(complex_positions)
    if n_receptor <= 0 or n_receptor >= n:
        raise RuntimeError(
            f"MM-GBSA receptor atom count {n_receptor} is not a subset of complex ({n} atoms)."
        )
    return complex_positions[:n_receptor], complex_positions[n_receptor:]


def score_mmgbsa_frame(
    *,
    complex_topology,
    complex_system,
    receptor_topology,
    receptor_system,
    ligand_topology,
    ligand_system,
    complex_positions,
    create_simulation: Callable,
    n_receptor: int | None = None,
    time_ps: float | None = None,
    frame: int | None = None,
    solvent: str = "gbn2",
    salt_m: float = 0.15,
    protein_ff: str = "",
    ligand_ff: str = "",
    charge_tag: str = "",
    note: str = "",
) -> MMGBSAResult:
    """1-trajectory MM-GBSA: three GB calculations on one set of complex coordinates."""
    n_rec = int(n_receptor if n_receptor is not None else receptor_topology.getNumAtoms())
    rec_pos, lig_pos = slice_complex_positions(complex_positions, n_rec)
    if ligand_topology.getNumAtoms() != len(lig_pos):
        raise RuntimeError(
            "MM-GBSA ligand atom count "
            f"({ligand_topology.getNumAtoms()}) does not match complex slice ({len(lig_pos)})."
        )
    complex_e = score_system_terms(
        complex_topology, complex_system, complex_positions, create_simulation
    )
    receptor_e = score_system_terms(receptor_topology, receptor_system, rec_pos, create_simulation)
    ligand_e = score_system_terms(ligand_topology, ligand_system, lig_pos, create_simulation)
    return MMGBSAResult(
        complex=complex_e,
        receptor=receptor_e,
        ligand=ligand_e,
        time_ps=time_ps,
        frame=frame,
        solvent=solvent,
        salt_m=salt_m,
        protein_ff=protein_ff,
        ligand_ff=ligand_ff,
        charge_tag=charge_tag,
        note=note,
    )


class MMGBSAScorer:
    """Reuse three OpenMM Contexts to score many frames without rebuilding systems."""

    def __init__(
        self,
        *,
        complex_topology,
        complex_system,
        receptor_topology,
        receptor_system,
        ligand_topology,
        ligand_system,
        create_simulation: Callable,
        solvent: str = "gbn2",
        salt_m: float = 0.15,
        protein_ff: str = "",
        ligand_ff: str = "",
        charge_tag: str = "",
        note: str = "",
    ) -> None:
        from openmm import VerletIntegrator, unit

        self._n_receptor = int(receptor_topology.getNumAtoms())
        self._n_ligand = int(ligand_topology.getNumAtoms())
        self._solvent = solvent
        self._salt_m = salt_m
        self._protein_ff = protein_ff
        self._ligand_ff = ligand_ff
        self._charge_tag = charge_tag
        self._note = note
        assign_force_groups(complex_system)
        assign_force_groups(receptor_system)
        assign_force_groups(ligand_system)
        dt = 0.001 * unit.picoseconds
        self._complex_system = complex_system
        self._receptor_system = receptor_system
        self._ligand_system = ligand_system
        self._complex = create_simulation(complex_topology, complex_system, VerletIntegrator(dt))
        self._receptor = create_simulation(receptor_topology, receptor_system, VerletIntegrator(dt))
        self._ligand = create_simulation(ligand_topology, ligand_system, VerletIntegrator(dt))

    def score(
        self,
        complex_positions,
        *,
        time_ps: float | None = None,
        frame: int | None = None,
    ) -> MMGBSAResult:
        rec_pos, lig_pos = slice_complex_positions(complex_positions, self._n_receptor)
        if len(lig_pos) != self._n_ligand:
            raise RuntimeError(
                f"MM-GBSA ligand slice ({len(lig_pos)}) != topology ({self._n_ligand})."
            )
        self._complex.context.setPositions(complex_positions)
        self._receptor.context.setPositions(rec_pos)
        self._ligand.context.setPositions(lig_pos)
        return MMGBSAResult(
            complex=terms_from_context(self._complex.context, self._complex_system),
            receptor=terms_from_context(self._receptor.context, self._receptor_system),
            ligand=terms_from_context(self._ligand.context, self._ligand_system),
            time_ps=time_ps,
            frame=frame,
            solvent=self._solvent,
            salt_m=self._salt_m,
            protein_ff=self._protein_ff,
            ligand_ff=self._ligand_ff,
            charge_tag=self._charge_tag,
            note=self._note,
        )


def _fmt(value: float) -> str:
    return f"{value:12.2f}"


def format_mmgbsa_report(result: MMGBSAResult, *, extra_lines: Sequence[str] = ()) -> str:
    """Amber-style table for one frame (kcal/mol). Not experimental ΔG."""
    delta = result.delta
    rows = (
        ("VDWAALS", "vdw"),
        ("EEL", "elec"),
        ("EGB", "gb"),
        ("ESURF", "sa"),
        ("E_BONDED", "bonded"),
        ("GGAS", "ggas"),
        ("GSOLV", "gsolv"),
        ("TOTAL", "total"),
    )
    lines = [
        "MM-GBSA (1-trajectory, OpenMM implicit solvent)",
        "Energies are kcal/mol. TOTAL is ΔG_MM-GBSA without entropy (−TΔS omitted).",
        "This is a ranking score, not an experimental binding free energy.",
        f"GB model: {result.solvent.upper()}   salt: {result.salt_m:.2f} M",
    ]
    if result.protein_ff or result.ligand_ff:
        bits = [b for b in (result.protein_ff, result.ligand_ff, result.charge_tag) if b]
        lines.append("Force field: " + " ".join(bits))
    if result.frame is not None or result.time_ps is not None:
        fr = f"frame {result.frame}" if result.frame is not None else "frame"
        t = f"{result.time_ps:.2f} ps" if result.time_ps is not None else ""
        lines.append(" ".join(p for p in (fr, t) if p))
    if result.note:
        lines.append(result.note)
    lines.extend(extra_lines)
    lines.append("")
    lines.append(f"{'':10} {'COMPLEX':>12} {'RECEPTOR':>12} {'LIGAND':>12} {'DELTA':>12}")
    for label, attr in rows:
        c = getattr(result.complex, attr)
        r = getattr(result.receptor, attr)
        lig = getattr(result.ligand, attr)
        d = getattr(delta, attr)
        lines.append(f"{label:10} {_fmt(c)} {_fmt(r)} {_fmt(lig)} {_fmt(d)}")
    return "\n".join(lines) + "\n"


def average_mmgbsa_results(results: Sequence[MMGBSAResult]) -> tuple[MMGBSATerms, MMGBSATerms]:
    """Mean and sample standard deviation of Δ terms (std is 0 for a single frame)."""
    if not results:
        raise ValueError("No MM-GBSA frames to average.")
    deltas = [item.delta for item in results]
    names = ("total", "bonded", "vdw", "elec", "gb", "sa", "other")
    mean_kw: dict[str, float] = {}
    std_kw: dict[str, float] = {}
    for name in names:
        values = [getattr(item, name) for item in deltas]
        mean_kw[name] = statistics.fmean(values)
        std_kw[name] = statistics.stdev(values) if len(values) > 1 else 0.0
    return MMGBSATerms(**mean_kw), MMGBSATerms(**std_kw)


def format_mmgbsa_ensemble_report(
    results: Sequence[MMGBSAResult],
    *,
    extra_lines: Sequence[str] = (),
) -> str:
    """Mean ± SD over snapshots, plus the last-frame table."""
    if not results:
        return "No MM-GBSA snapshots.\n"
    mean, std = average_mmgbsa_results(results)
    first = results[0]
    header = format_mmgbsa_report(
        replace(first, note=first.note),
        extra_lines=(
            f"Snapshots: {len(results)}",
            *extra_lines,
        ),
    )
    lines = [
        header.rstrip(),
        "",
        f"{'DELTA mean':10} {_fmt(mean.total)}   (n={len(results)})",
        f"{'DELTA sd':10} {_fmt(std.total)}",
        f"{'VDWAALS':10} {_fmt(mean.vdw)} ± {_fmt(std.vdw).strip()}",
        f"{'EEL':10} {_fmt(mean.elec)} ± {_fmt(std.elec).strip()}",
        f"{'EGB':10} {_fmt(mean.gb)} ± {_fmt(std.gb).strip()}",
        f"{'ESURF':10} {_fmt(mean.sa)} ± {_fmt(std.sa).strip()}",
        f"{'GGAS':10} {_fmt(mean.ggas)} ± {_fmt(std.ggas).strip()}",
        f"{'GSOLV':10} {_fmt(mean.gsolv)} ± {_fmt(std.gsolv).strip()}",
        "",
        "Last snapshot:",
        format_mmgbsa_report(results[-1]).rstrip(),
    ]
    return "\n".join(lines) + "\n"


def write_mmgbsa_csv(path: Path, results: Sequence[MMGBSAResult]) -> None:
    """One row per snapshot with complex/receptor/ligand/delta totals and pieces."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "frame",
        "time_ps",
        "dG",
        "vdw",
        "eel",
        "egb",
        "esurf",
        "bonded",
        "ggas",
        "gsolv",
        "E_complex",
        "E_receptor",
        "E_ligand",
    )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in results:
            delta = item.delta
            writer.writerow(
                {
                    "frame": item.frame if item.frame is not None else "",
                    "time_ps": "" if item.time_ps is None else f"{item.time_ps:.4f}",
                    "dG": f"{delta.total:.6f}",
                    "vdw": f"{delta.vdw:.6f}",
                    "eel": f"{delta.elec:.6f}",
                    "egb": f"{delta.gb:.6f}",
                    "esurf": f"{delta.sa:.6f}",
                    "bonded": f"{delta.bonded:.6f}",
                    "ggas": f"{delta.ggas:.6f}",
                    "gsolv": f"{delta.gsolv:.6f}",
                    "E_complex": f"{item.complex.total:.6f}",
                    "E_receptor": f"{item.receptor.total:.6f}",
                    "E_ligand": f"{item.ligand.total:.6f}",
                }
            )
