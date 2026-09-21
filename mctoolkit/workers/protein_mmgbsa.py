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

"""1-trajectory MM-GBSA on a Protein Viewer complex (OpenMM GBn2/OBC2)."""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from ..md.mmgbsa import MMGBSAScorer, format_mmgbsa_report
from .pdb_fixer_runtime import _configure_openmm_runtime
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .protein_openmm_holo import HoloOpenMMWork, prepare_holo_work
from .protein_prepare import drain_prepare_log_file
from .protein_prepare_amber import _ligand_ff_tag, build_gaff_split_prmtops
from .protein_prepare_constants import (
    _DEFAULT_CA_K_KCAL,
    _DEFAULT_MIN_ITERS,
    _GB_SALT_M,
    _LIGAND_FF_GAFF2,
    _OPENMM_PLATFORM_AUTO,
    _PROTEIN_FF_AMBER14,
    _RESTRAINT_BACKBONE_LIGAND,
    _SOLVENT_GBN2,
    ResidueKey,
)
from .protein_prepare_io import (
    _is_cif_fmt,
    _prepared_output_path,
    append_prepare_log_file,
    bind_prepare_log,
    log_prepare,
    unbind_prepare_log,
)
from .protein_prepare_minimize import (
    _amber_holo_system,
    _create_openmm_simulation,
    _ligand_chem_tables,
)
from .protein_prepare_runtime import _write_prepared_output

_OPENMM_VERSION_HINT = (
    "MM-GBSA subprocess crashed. On Windows this is often caused by OpenMM 8.3+ "
    "(native crash during hydrogen placement). Install a supported build:\n"
    "  pip install 'openmm>=8.2,<8.3' pdbfixer pdb2pqr"
)


@dataclass(frozen=True)
class ProteinMMGBSARequest:
    input_path: str
    report_path: str
    protein_ff: str = _PROTEIN_FF_AMBER14
    ligand_ff: str = _LIGAND_FF_GAFF2
    solvent: str = _SOLVENT_GBN2
    salt_m: float = _GB_SALT_M
    openmm_platform: str = _OPENMM_PLATFORM_AUTO
    ligand_smiles: str = ""
    ligand_ref_path: str = ""
    ligand_keys: tuple[ResidueKey, ...] = ()
    keep_water: bool = False
    minimize_first: bool = True
    restraint_set: str = _RESTRAINT_BACKBONE_LIGAND
    restraint_k_kcal_per_ang2: float = _DEFAULT_CA_K_KCAL
    max_iterations: int = _DEFAULT_MIN_ITERS
    structure_output_path: str = ""
    output_format: str = "cif"


@dataclass(frozen=True)
class ProteinMMGBSAJobResult:
    report_path: str
    structure_path: str = ""
    summary: str = ""
    delta_total: float = 0.0


def _write_structure_overlay(
    work: HoloOpenMMWork,
    source_text: str,
    dest: Path,
    *,
    remarks: list[str],
    output_format: str,
) -> Path:
    chem_atoms, chem_bonds = _ligand_chem_tables(
        source_text,
        fmt=work.work_fmt,
        keep_ligand=True,
        ligand_keys=work.ligand_keys,
        input_text=work.input_text,
        input_fmt=work.input_fmt,
    )
    out_fmt = (output_format or "cif").lower()
    out_file = _prepared_output_path(dest, out_fmt)
    _write_prepared_output(
        source_text,
        out_file,
        fmt=work.work_fmt,
        remarks=remarks,
        chem_atoms=chem_atoms,
        chem_bonds=chem_bonds,
        output_format=out_fmt,
    )
    return out_file


def _create_sim(topology, system, integrator, *, platform: str):
    return _create_openmm_simulation(topology, system, integrator, preferred=platform)


def _minimize_complex_system(
    topology,
    system,
    positions,
    *,
    req: ProteinMMGBSARequest,
    original_ca,
    ligand_keys,
):
    from openmm import LangevinMiddleIntegrator, unit

    from .protein_prepare_minimize import add_position_restraints

    add_position_restraints(
        system,
        topology,
        positions,
        scheme=req.restraint_set,
        k_kcal_per_ang2=float(req.restraint_k_kcal_per_ang2),
        original_ca_keys=original_ca,
        ligand_keys=ligand_keys,
    )
    integrator = LangevinMiddleIntegrator(
        300 * unit.kelvin, 1.0 / unit.picosecond, 0.002 * unit.picoseconds
    )
    simulation = _create_sim(topology, system, integrator, platform=req.openmm_platform)
    simulation.context.setPositions(positions)
    log_prepare(
        f"OpenMM: restrained minimization before MM-GBSA ({int(req.max_iterations)} iterations)…"
    )
    simulation.minimizeEnergy(maxIterations=int(req.max_iterations))
    return simulation.context.getState(getPositions=True).getPositions()


def _score_prepared_holo(
    work: HoloOpenMMWork,
    req: ProteinMMGBSARequest,
    *,
    complex_positions,
    tops,
    complex_sys,
    complex_top,
    rec_sys,
    rec_top,
    lig_sys,
    lig_top,
    solvent: str,
) -> tuple[str, float, str]:
    scorer = MMGBSAScorer(
        complex_topology=complex_top,
        complex_system=complex_sys,
        receptor_topology=rec_top,
        receptor_system=rec_sys,
        ligand_topology=lig_top,
        ligand_system=lig_sys,
        create_simulation=lambda top, sys, integ: _create_sim(
            top, sys, integ, platform=req.openmm_platform
        ),
        solvent=solvent,
        salt_m=float(req.salt_m),
        protein_ff=req.protein_ff.upper(),
        ligand_ff=_ligand_ff_tag(req.ligand_ff),
        charge_tag=tops.charge_tag,
        note="Waters stripped." if not work.keep_water else "Crystal waters kept in the receptor.",
    )
    log_prepare("OpenMM: scoring MM-GBSA (complex − receptor − ligand)…")
    result = scorer.score(complex_positions, frame=0, time_ps=0.0)
    report = format_mmgbsa_report(result)
    report_path = Path(req.report_path).expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    log_prepare(f"ΔG_MM-GBSA = {result.delta.total:.2f} kcal/mol (no entropy)")
    return str(report_path), float(result.delta.total), report


def score_protein_mmgbsa(req: ProteinMMGBSARequest, on_log=None) -> ProteinMMGBSAJobResult:
    """Parameterize the complex and write a 1-trajectory MM-GBSA report."""
    token = bind_prepare_log(on_log)
    try:
        return _score_protein_mmgbsa(req)
    finally:
        unbind_prepare_log(token)


def _score_protein_mmgbsa(req: ProteinMMGBSARequest) -> ProteinMMGBSAJobResult:
    from .protein_prepare_io import _write_openmm_structure
    from .protein_prepare_minimize import _normalize_solvent

    _configure_openmm_runtime()
    work = prepare_holo_work(
        input_path=req.input_path,
        ligand_ff=req.ligand_ff,
        ligand_smiles=req.ligand_smiles,
        ligand_ref_path=req.ligand_ref_path,
        ligand_keys=req.ligand_keys,
        keep_water=req.keep_water,
        require_gaff=True,
    )
    log_prepare("AmberTools: building complex/receptor/ligand topologies for MM-GBSA…")
    tops = build_gaff_split_prmtops(
        work.structure_path,
        ligand_mols=work.ligand_mols,
        ligand_keys=work.ligand_keys,
        keep_water=work.keep_water,
        protein_ff=req.protein_ff,
        ligand_ff=req.ligand_ff,
        solvent=req.solvent,
        work_dir=work.work_dir,
    )
    solvent = _normalize_solvent(req.solvent)
    complex_sys, complex_top, complex_pos, _lbl = _amber_holo_system(
        tops.complex_prmtop, tops.complex_inpcrd, solvent=solvent, salt_m=float(req.salt_m)
    )
    rec_sys, rec_top, _rec_pos, _ = _amber_holo_system(
        tops.receptor_prmtop, tops.receptor_inpcrd, solvent=solvent, salt_m=float(req.salt_m)
    )
    lig_sys, lig_top, _lig_pos, _ = _amber_holo_system(
        tops.ligand_prmtop, tops.ligand_inpcrd, solvent=solvent, salt_m=float(req.salt_m)
    )
    remarks = ["4 OPENMM MM-GBSA"]
    positions = complex_pos
    if req.minimize_first:
        min_sys, min_top, min_pos, _ = _amber_holo_system(
            tops.complex_prmtop, tops.complex_inpcrd, solvent=solvent, salt_m=float(req.salt_m)
        )
        positions = _minimize_complex_system(
            min_top,
            min_sys,
            min_pos,
            req=req,
            original_ca=work.original_ca,
            ligand_keys=work.ligand_keys,
        )
    dest = (req.structure_output_path or "").strip()
    structure_out = ""
    if dest and req.minimize_first:
        min_path = work.work_dir / f"minimized{work.work_ext}"
        _write_openmm_structure(
            complex_top,
            positions,
            min_path,
            remarks=remarks,
            chem_source=work.structure_text if _is_cif_fmt(work.work_fmt) else "",
        )
        log_prepare("Writing minimized complex…")
        structure_out = str(
            _write_structure_overlay(
                work,
                min_path.read_text(encoding="utf-8"),
                Path(dest),
                remarks=remarks,
                output_format=req.output_format,
            )
        )
    report_path, delta, summary = _score_prepared_holo(
        work,
        req,
        complex_positions=positions,
        tops=tops,
        complex_sys=complex_sys,
        complex_top=complex_top,
        rec_sys=rec_sys,
        rec_top=rec_top,
        lig_sys=lig_sys,
        lig_top=lig_top,
        solvent=solvent,
    )
    return ProteinMMGBSAJobResult(
        report_path=report_path,
        structure_path=structure_out,
        summary=summary,
        delta_total=delta,
    )


def mp_score_protein_mmgbsa(
    req: ProteinMMGBSARequest, log_path: str | None = None
) -> tuple[bool, object]:
    """Child-process entry: keep OpenMM/AmberTools out of the GUI process."""

    def _log(message: str) -> None:
        append_prepare_log_file(log_path, message)

    try:
        return True, score_protein_mmgbsa(req, on_log=_log)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or "MM-GBSA failed."


class ProteinMMGBSASignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class ProteinMMGBSAWorker(QRunnable):
    """Run MM-GBSA in an isolated subprocess."""

    def __init__(
        self,
        req: ProteinMMGBSARequest,
        *,
        signals: ProteinMMGBSASignals,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.req = req
        self.signals = signals
        self.cancel_event = cancel_event

    def run(self) -> None:
        cancel_ev = self.cancel_event
        try:
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            ex = register_process_pool(ProcessPoolExecutor(max_workers=1))
            log_path: str | None = None
            try:
                fd, log_path = tempfile.mkstemp(prefix="mctoolkit_mmgbsa_log_", suffix=".txt")
                os.close(fd)
            except OSError:
                log_path = None
            seen = [0]
            try:
                future = ex.submit(mp_score_protein_mmgbsa, self.req, log_path)
                pending = {future}
                while pending:
                    drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
                    if should_terminate_process_pool(cancel_ev):
                        future.cancel()
                        self.signals.failed.emit("Cancelled.")
                        return
                    _done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
                if future.cancelled():
                    self.signals.failed.emit("Cancelled.")
                    return
                ok, msg = future.result()
                drain_prepare_log_file(log_path, seen, self.signals.progress.emit)
            finally:
                shutdown_process_pool_executor(
                    ex, kill_workers=should_terminate_process_pool(cancel_ev)
                )
                if log_path:
                    with contextlib.suppress(OSError):
                        os.unlink(log_path)
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            if ok:
                self.signals.finished.emit(msg)
            else:
                self.signals.failed.emit(str(msg))
        except BrokenExecutor:
            self.signals.failed.emit(_OPENMM_VERSION_HINT)
        except Exception as exc:  # noqa: BLE001
            text = str(exc) or "MM-GBSA failed."
            if "terminated abruptly" in text.lower():
                self.signals.failed.emit(_OPENMM_VERSION_HINT)
            else:
                self.signals.failed.emit(text)
