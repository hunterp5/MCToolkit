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

"""Implicit-solvent OpenMM MD of a Protein Viewer complex, optional MM-GBSA."""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from ..md.implicit_md import (
    ImplicitMDConfig,
    align_solute_com,
    run_implicit_md,
)
from ..md.mmgbsa import (
    MMGBSAScorer,
    average_mmgbsa_results,
    format_mmgbsa_ensemble_report,
    write_mmgbsa_csv,
)
from .pdb_fixer_runtime import _configure_openmm_runtime
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .protein_openmm_holo import prepare_holo_work
from .protein_prepare import drain_prepare_log_file
from .protein_prepare_amber import _ligand_ff_tag, build_gaff_split_prmtops
from .protein_prepare_constants import (
    _DEFAULT_BOX_PADDING_A,
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
    append_prepare_log_file,
    bind_prepare_log,
    log_prepare,
    unbind_prepare_log,
)
from .protein_prepare_minimize import (
    _amber_explicit_system,
    _amber_holo_system,
    _amber_topology_positions,
    _create_openmm_simulation,
    _is_explicit_solvent,
    add_position_restraints,
)
from .protein_mmgbsa import _write_structure_overlay

_OPENMM_VERSION_HINT = (
    "MD subprocess crashed. On Windows this is often caused by OpenMM 8.3+ "
    "(native crash during hydrogen placement). Install a supported build:\n"
    "  pip install 'openmm>=8.2,<8.3' pdbfixer pdb2pqr"
)


@dataclass(frozen=True)
class ProteinMDRequest:
    input_path: str
    output_path: str
    report_path: str = ""
    dcd_path: str = ""
    csv_path: str = ""
    protein_ff: str = _PROTEIN_FF_AMBER14
    ligand_ff: str = _LIGAND_FF_GAFF2
    solvent: str = _SOLVENT_GBN2
    salt_m: float = _GB_SALT_M
    openmm_platform: str = _OPENMM_PLATFORM_AUTO
    ligand_smiles: str = ""
    ligand_ref_path: str = ""
    ligand_keys: tuple[ResidueKey, ...] = ()
    keep_water: bool = False
    output_format: str = "cif"
    temperature_k: float = 300.0
    friction_per_ps: float = 1.0
    timestep_fs: float = 2.0
    minimize_iterations: int = _DEFAULT_MIN_ITERS
    equilibration_ps: float = 10.0
    production_ps: float = 100.0
    snapshot_ps: float = 10.0
    restraint_set: str = _RESTRAINT_BACKBONE_LIGAND
    restraint_k_eq: float = _DEFAULT_CA_K_KCAL
    restraint_k_prod: float = 0.0
    score_mmgbsa: bool = True
    box_padding_a: float = _DEFAULT_BOX_PADDING_A
    checkpoint_path: str = ""
    checkpoint_ps: float = 20.0
    resume: bool = False


@dataclass(frozen=True)
class ProteinMDJobResult:
    structure_path: str
    report_path: str = ""
    dcd_path: str = ""
    csv_path: str = ""
    summary: str = ""
    n_snapshots: int = 0
    delta_mean: float | None = None


def run_protein_md(req: ProteinMDRequest, on_log=None) -> ProteinMDJobResult:
    """Langevin MD (GBSA or TIP3P PME); optional snapshot MM-GBSA."""
    token = bind_prepare_log(on_log)
    try:
        return _run_protein_md(req)
    finally:
        unbind_prepare_log(token)


def _run_protein_md(req: ProteinMDRequest) -> ProteinMDJobResult:
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
    explicit = _is_explicit_solvent(req.solvent)
    gb_solvent = _SOLVENT_GBN2 if explicit else _normalize_solvent(req.solvent)
    padding = float(req.box_padding_a) if explicit else 0.0
    log_prepare(
        "AmberTools: building topologies for "
        + ("explicit-solvent PME MD…" if explicit else "implicit MD…")
    )
    tops = build_gaff_split_prmtops(
        work.structure_path,
        ligand_mols=work.ligand_mols,
        ligand_keys=work.ligand_keys,
        keep_water=work.keep_water,
        protein_ff=req.protein_ff,
        ligand_ff=req.ligand_ff,
        solvent=gb_solvent,
        work_dir=work.work_dir,
        solvate_padding_a=padding,
        ion_conc_m=float(req.salt_m) if explicit else 0.0,
    )
    if explicit:
        if tops.solvated_prmtop is None or tops.solvated_inpcrd is None:
            raise RuntimeError("tleap did not write a solvated prmtop for PME MD.")
        dry_top, dry_pos = _amber_topology_positions(tops.complex_prmtop, tops.complex_inpcrd)
        n_solute = int(dry_top.getNumAtoms())
        md_sys, md_top, md_pos, lbl = _amber_explicit_system(
            tops.solvated_prmtop,
            tops.solvated_inpcrd,
            temperature_k=float(req.temperature_k),
        )
        log_prepare(f"OpenMM: {lbl} ({md_top.getNumAtoms()} atoms, {n_solute} solute)")
    else:
        dry_top = None
        dry_pos = None
        n_solute = 0
        md_sys, md_top, md_pos, lbl = _amber_holo_system(
            tops.complex_prmtop, tops.complex_inpcrd, solvent=gb_solvent, salt_m=float(req.salt_m)
        )
        log_prepare(f"OpenMM: {lbl}")
    add_position_restraints(
        md_sys,
        md_top,
        md_pos,
        scheme=req.restraint_set,
        k_kcal_per_ang2=float(req.restraint_k_eq),
        original_ca_keys=work.original_ca,
        ligand_keys=work.ligand_keys,
    )
    scorer = None
    if req.score_mmgbsa:
        score_sys, score_top, _sp, _ = _amber_holo_system(
            tops.complex_prmtop, tops.complex_inpcrd, solvent=gb_solvent, salt_m=float(req.salt_m)
        )
        rec_sys, rec_top, _rp, _ = _amber_holo_system(
            tops.receptor_prmtop, tops.receptor_inpcrd, solvent=gb_solvent, salt_m=float(req.salt_m)
        )
        lig_sys, lig_top, _lp, _ = _amber_holo_system(
            tops.ligand_prmtop, tops.ligand_inpcrd, solvent=gb_solvent, salt_m=float(req.salt_m)
        )
        note = "1-trajectory MM-GBSA; −TΔS omitted. "
        if explicit:
            note += "Snapshots stripped of TIP3P/ions, then GBn2. "
        note += "Waters stripped." if not work.keep_water else "Crystal waters kept."
        scorer = MMGBSAScorer(
            complex_topology=score_top,
            complex_system=score_sys,
            receptor_topology=rec_top,
            receptor_system=rec_sys,
            ligand_topology=lig_top,
            ligand_system=lig_sys,
            create_simulation=lambda top, sys, integ: _create_openmm_simulation(
                top, sys, integ, preferred=req.openmm_platform
            ),
            solvent=gb_solvent,
            salt_m=float(req.salt_m),
            protein_ff=req.protein_ff.upper(),
            ligand_ff=_ligand_ff_tag(req.ligand_ff),
            charge_tag=tops.charge_tag,
            note=note,
        )
    dcd_path = (req.dcd_path or "").strip()
    md_result = run_implicit_md(
        topology=md_top,
        system=md_sys,
        positions=md_pos,
        create_simulation=lambda top, sys, integ: _create_openmm_simulation(
            top, sys, integ, preferred=req.openmm_platform
        ),
        config=ImplicitMDConfig(
            temperature_k=float(req.temperature_k),
            friction_per_ps=float(req.friction_per_ps),
            timestep_fs=float(req.timestep_fs),
            minimize_iterations=int(req.minimize_iterations),
            equilibration_ps=float(req.equilibration_ps),
            production_ps=float(req.production_ps),
            snapshot_ps=float(req.snapshot_ps),
            restraint_k_eq=float(req.restraint_k_eq),
            restraint_k_prod=float(req.restraint_k_prod),
            dcd_path=dcd_path,
            solute_atoms=n_solute,
            checkpoint_path=(req.checkpoint_path or "").strip(),
            checkpoint_ps=float(req.checkpoint_ps),
            resume=bool(req.resume),
            wrap_dcd=explicit,
        ),
        scorer=scorer,
        on_log=log_prepare,
    )
    overlay_pos = md_result.positions
    overlay_top = md_top
    if explicit:
        overlay_top = dry_top
        overlay_pos = align_solute_com(overlay_pos, dry_pos)
    last_path = work.work_dir / f"md_last{work.work_ext}"
    solvent_tag = "TIP3P-PME" if explicit else gb_solvent.upper()
    remarks = [
        "4 OPENMM MD "
        f"{req.production_ps:.1f}PS {req.protein_ff.upper()} {_ligand_ff_tag(req.ligand_ff)} "
        f"{solvent_tag}"
    ]
    _write_openmm_structure(
        overlay_top,
        overlay_pos,
        last_path,
        remarks=remarks,
        chem_source=work.structure_text if _is_cif_fmt(work.work_fmt) else "",
    )
    out_fmt = (req.output_format or "cif").lower()
    out_file = _write_structure_overlay(
        work,
        last_path.read_text(encoding="utf-8"),
        Path(req.output_path),
        remarks=remarks,
        output_format=out_fmt,
    )
    report_path = (req.report_path or "").strip()
    csv_path = (req.csv_path or "").strip()
    summary = ""
    delta_mean = None
    if md_result.mmgbsa:
        extra = [
            f"Production: {req.production_ps:.1f} ps   snapshot every {req.snapshot_ps:.1f} ps",
        ]
        if explicit:
            extra.append(
                f"MD solvent: TIP3P PME NPT ({req.box_padding_a:.1f} Å padding). "
                "MM-GBSA on solute only (GBn2)."
            )
        summary = format_mmgbsa_ensemble_report(md_result.mmgbsa, extra_lines=tuple(extra))
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(summary, encoding="utf-8", newline="\n")
        if csv_path:
            write_mmgbsa_csv(Path(csv_path), md_result.mmgbsa)
        mean, _std = average_mmgbsa_results(md_result.mmgbsa)
        delta_mean = mean.total
        log_prepare(
            f"MM-GBSA mean ΔG = {mean.total:.2f} kcal/mol over {len(md_result.mmgbsa)} snapshot(s)"
        )
    elif report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            ("Explicit-solvent" if explicit else "Implicit-solvent")
            + " MD finished. MM-GBSA scoring was not requested.\n",
            encoding="utf-8",
            newline="\n",
        )
    log_prepare(f"Writing last frame → {Path(str(out_file)).name}")
    return ProteinMDJobResult(
        structure_path=str(out_file),
        report_path=report_path,
        dcd_path=md_result.dcd_path,
        csv_path=csv_path if md_result.mmgbsa else "",
        summary=summary,
        n_snapshots=len(md_result.mmgbsa),
        delta_mean=delta_mean,
    )


def mp_run_protein_md(req: ProteinMDRequest, log_path: str | None = None) -> tuple[bool, object]:
    """Child-process entry: keep OpenMM/AmberTools out of the GUI process."""

    def _log(message: str) -> None:
        append_prepare_log_file(log_path, message)

    try:
        return True, run_protein_md(req, on_log=_log)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc) or "Molecular dynamics failed."


class ProteinMDSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class ProteinMDWorker(QRunnable):
    """Run implicit MD in an isolated subprocess."""

    def __init__(
        self,
        req: ProteinMDRequest,
        *,
        signals: ProteinMDSignals,
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
                fd, log_path = tempfile.mkstemp(prefix="mctoolkit_md_log_", suffix=".txt")
                os.close(fd)
            except OSError:
                log_path = None
            seen = [0]
            try:
                future = ex.submit(mp_run_protein_md, self.req, log_path)
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
            text = str(exc) or "Molecular dynamics failed."
            if "terminated abruptly" in text.lower():
                self.signals.failed.emit(_OPENMM_VERSION_HINT)
            else:
                self.signals.failed.emit(text)
