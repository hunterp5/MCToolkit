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

"""Langevin MD (implicit GBSA or explicit PME) with optional snapshot MM-GBSA."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..platform_support.exception_policy import log_swallowed_exception
from .mmgbsa import MMGBSAResult, MMGBSAScorer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImplicitMDConfig:
    """Langevin protocol for a GBn2/OBC2 or solvated PME holo system."""

    temperature_k: float = 300.0
    friction_per_ps: float = 1.0
    timestep_fs: float = 2.0
    minimize_iterations: int = 400
    equilibration_ps: float = 10.0
    production_ps: float = 100.0
    snapshot_ps: float = 10.0
    restraint_k_eq: float = 10.0
    restraint_k_prod: float = 0.0
    dcd_path: str = ""
    log_every_ps: float = 1.0
    solute_atoms: int = 0
    checkpoint_path: str = ""
    checkpoint_ps: float = 20.0
    resume: bool = False
    wrap_dcd: bool = False


@dataclass
class ImplicitMDResult:
    """Last production coordinates plus optional MM-GBSA snapshots."""

    positions: object
    n_eq_steps: int
    n_prod_steps: int
    dcd_path: str = ""
    mmgbsa: list[MMGBSAResult] = field(default_factory=list)
    resumed: bool = False
    checkpoint_path: str = ""


def _steps_for_ps(time_ps: float, timestep_fs: float) -> int:
    dt_ps = float(timestep_fs) / 1000.0
    if dt_ps <= 0:
        raise RuntimeError("MD timestep must be positive.")
    return max(0, int(round(float(time_ps) / dt_ps)))


def _kcal_pe(state) -> float:
    from openmm import unit

    return float(state.getPotentialEnergy().value_in_unit(unit.kilocalories_per_mole))


def slice_solute_positions(positions, n_solute: int):
    """Keep the leading dry-complex atoms (tleap solvateBox appends solvent)."""
    n_sol = int(n_solute)
    if n_sol <= 0:
        return positions
    n = len(positions)
    if n_sol > n:
        raise RuntimeError(f"Solute atom count {n_sol} exceeds system size ({n} atoms).")
    if n_sol == n:
        return positions
    return positions[:n_sol]


def _xyz_nm(point) -> tuple[float, float, float]:
    if hasattr(point, "value_in_unit"):
        from openmm import unit

        xyz = point.value_in_unit(unit.nanometer)
        return float(xyz[0]), float(xyz[1]), float(xyz[2])
    return float(point[0]), float(point[1]), float(point[2])


def _com_nm(positions) -> tuple[float, float, float]:
    n = len(positions)
    if n <= 0:
        return (0.0, 0.0, 0.0)
    xs = ys = zs = 0.0
    for point in positions:
        x, y, z = _xyz_nm(point)
        xs += x
        ys += y
        zs += z
    inv = 1.0 / n
    return (xs * inv, ys * inv, zs * inv)


def align_solute_com(positions, reference) -> list:
    """Translate *positions* so the solute COM matches *reference*."""
    from openmm import Vec3, unit

    dx, dy, dz = (a - b for a, b in zip(_com_nm(reference), _com_nm(positions), strict=True))
    out = []
    for point in positions:
        x, y, z = _xyz_nm(point)
        out.append(Vec3(x + dx, y + dy, z + dz) * unit.nanometer)
    return out


def checkpoint_meta_path(checkpoint_path: str | Path) -> Path:
    rec = Path(checkpoint_path)
    return rec.with_name(rec.name + ".json")


def read_checkpoint_meta(checkpoint_path: str | Path) -> dict:
    meta = checkpoint_meta_path(checkpoint_path)
    if not meta.is_file():
        return {}
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_checkpoint_meta(
    checkpoint_path: str | Path,
    *,
    n_eq_steps: int,
    n_prod_target: int,
    timestep_fs: float,
    current_step: int,
) -> None:
    rec = checkpoint_meta_path(checkpoint_path)
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(
        json.dumps(
            {
                "n_eq_steps": int(n_eq_steps),
                "n_prod_target": int(n_prod_target),
                "timestep_fs": float(timestep_fs),
                "current_step": int(current_step),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def production_steps_done(current_step: int, n_eq_steps: int) -> int:
    return max(0, int(current_step) - int(n_eq_steps))


def run_implicit_md(
    *,
    topology,
    system,
    positions,
    create_simulation: Callable,
    config: ImplicitMDConfig,
    scorer: MMGBSAScorer | None = None,
    on_log: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ImplicitMDResult:
    """Minimize, restrained eq, then production. Scores MM-GBSA when *scorer* is set."""
    from openmm import LangevinMiddleIntegrator, unit
    from openmm.app import DCDReporter

    def _log(message: str) -> None:
        if on_log is not None:
            on_log(message)

    def _cancelled() -> bool:
        return bool(should_cancel is not None and should_cancel())

    dt = float(config.timestep_fs) * unit.femtoseconds
    integrator = LangevinMiddleIntegrator(
        float(config.temperature_k) * unit.kelvin,
        float(config.friction_per_ps) / unit.picosecond,
        dt,
    )
    simulation = create_simulation(topology, system, integrator)
    simulation.context.setPositions(positions)
    chk_path = (config.checkpoint_path or "").strip()
    n_eq = _steps_for_ps(config.equilibration_ps, config.timestep_fs)
    n_prod = _steps_for_ps(config.production_ps, config.timestep_fs)
    n_snap = _steps_for_ps(config.snapshot_ps, config.timestep_fs) if scorer is not None else 0
    n_log = max(1, _steps_for_ps(config.log_every_ps, config.timestep_fs))
    n_chk = _steps_for_ps(config.checkpoint_ps, config.timestep_fs) if chk_path else 0
    chunk = max(1, min(n_log, 500))
    k_unit = unit.kilocalories_per_mole / unit.angstroms**2
    resumed = False
    n_eq_recorded = n_eq

    def _set_k(kcal: float) -> None:
        try:
            simulation.context.setParameter("k", float(kcal) * k_unit)
        except Exception:  # noqa: BLE001
            log_swallowed_exception(logger, "MD restraint parameter k is not in this system")

    def _save_chk() -> None:
        if not chk_path:
            return
        rec = Path(chk_path)
        rec.parent.mkdir(parents=True, exist_ok=True)
        simulation.saveCheckpoint(str(rec))
        write_checkpoint_meta(
            rec,
            n_eq_steps=n_eq_recorded,
            n_prod_target=n_prod,
            timestep_fs=float(config.timestep_fs),
            current_step=int(simulation.currentStep),
        )

    def _score_now(time_ps: float, frame: int) -> MMGBSAResult:
        pos = simulation.context.getState(getPositions=True).getPositions()
        pos = slice_solute_positions(pos, int(config.solute_atoms))
        return scorer.score(pos, time_ps=time_ps, frame=frame)

    def _advance(n_steps: int, *, label: str) -> None:
        remaining = int(n_steps)
        done = 0
        while remaining > 0:
            if _cancelled():
                raise RuntimeError("Cancelled.")
            take = min(chunk, remaining)
            simulation.step(take)
            remaining -= take
            done += take
            if remaining == 0 or done % n_log == 0:
                state = simulation.context.getState(getEnergy=True)
                time_ps = done * float(config.timestep_fs) / 1000.0
                _log(f"OpenMM MD: {label} {time_ps:.1f} ps  E={_kcal_pe(state):.1f} kcal/mol")

    if _cancelled():
        raise RuntimeError("Cancelled.")
    if config.resume and chk_path and Path(chk_path).is_file():
        simulation.loadCheckpoint(chk_path)
        meta = read_checkpoint_meta(chk_path)
        n_eq_recorded = int(meta.get("n_eq_steps", n_eq))
        resumed = True
        _log(
            f"OpenMM MD: resumed checkpoint {Path(chk_path).name} "
            f"at step {int(simulation.currentStep)}"
        )
    else:
        n_min = int(config.minimize_iterations)
        if n_min > 0:
            _log(f"OpenMM MD: minimizing ({n_min} iterations)…")
            simulation.minimizeEnergy(maxIterations=n_min)
        try:
            simulation.context.setVelocitiesToTemperature(float(config.temperature_k) * unit.kelvin)
        except Exception:  # noqa: BLE001
            log_swallowed_exception(logger, "MD could not assign Maxwell–Boltzmann velocities")
        if n_eq:
            _set_k(float(config.restraint_k_eq))
            _log(
                f"OpenMM MD: equilibrating {config.equilibration_ps:.1f} ps "
                f"(k={config.restraint_k_eq:.1f} kcal/mol/Å²)…"
            )
            _advance(n_eq, label="eq")
        n_eq_recorded = int(simulation.currentStep)
        _save_chk()
    _set_k(float(config.restraint_k_prod))
    dcd_path = (config.dcd_path or "").strip()
    already = production_steps_done(int(simulation.currentStep), n_eq_recorded)
    remaining_prod = max(0, n_prod - already)
    if dcd_path and remaining_prod:
        interval = n_snap if n_snap > 0 else max(1, n_log)
        Path(dcd_path).parent.mkdir(parents=True, exist_ok=True)
        simulation.reporters.append(
            DCDReporter(dcd_path, interval, enforcePeriodicBox=bool(config.wrap_dcd))
        )
        if resumed:
            _log(
                f"OpenMM MD: writing DCD every {interval} steps → {Path(dcd_path).name} "
                "(resume starts a new DCD)"
            )
        else:
            _log(f"OpenMM MD: writing DCD every {interval} steps → {Path(dcd_path).name}")
    snapshots: list[MMGBSAResult] = []
    if remaining_prod:
        _log(
            f"OpenMM MD: production {config.production_ps:.1f} ps "
            f"(k={config.restraint_k_prod:.1f} kcal/mol/Å²"
            + (f", already {already} steps" if already else "")
            + ")…"
        )
        remaining = remaining_prod
        done = already
        next_snap = 0
        frame = 0
        if n_snap > 0:
            frame = done // n_snap
            next_snap = (frame + 1) * n_snap
        next_chk = 0
        if n_chk > 0:
            next_chk = ((done // n_chk) + 1) * n_chk if done else n_chk
        while remaining > 0:
            if _cancelled():
                _save_chk()
                raise RuntimeError("Cancelled.")
            take = min(chunk, remaining)
            if next_snap > 0:
                take = min(take, next_snap - done)
            if next_chk > 0:
                take = min(take, next_chk - done)
            simulation.step(take)
            remaining -= take
            done += take
            time_ps = done * float(config.timestep_fs) / 1000.0
            if remaining == 0 or done % n_log == 0:
                state = simulation.context.getState(getEnergy=True)
                _log(f"OpenMM MD: prod {time_ps:.1f} ps  E={_kcal_pe(state):.1f} kcal/mol")
            if next_snap > 0 and done >= next_snap:
                frame += 1
                snapshots.append(_score_now(time_ps, frame))
                _log(f"OpenMM MD: MM-GBSA snapshot {frame}  ΔG={snapshots[-1].delta.total:.2f}")
                next_snap += n_snap
            if next_chk > 0 and done >= next_chk:
                _save_chk()
                next_chk += n_chk
        _save_chk()
    elif already >= n_prod:
        _log("OpenMM MD: production already complete in the checkpoint")
    last = simulation.context.getState(getPositions=True).getPositions()
    last = slice_solute_positions(last, int(config.solute_atoms))
    _log("OpenMM MD: finished")
    return ImplicitMDResult(
        positions=last,
        n_eq_steps=n_eq_recorded,
        n_prod_steps=n_prod,
        dcd_path=dcd_path if dcd_path and n_prod else "",
        mmgbsa=snapshots,
        resumed=resumed,
        checkpoint_path=chk_path,
    )
