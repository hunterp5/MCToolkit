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

"""Qt signal objects shared by background workers."""

from PySide6.QtCore import QObject, Signal


def emit_partial_results_if_cancelled(
    signals: "WorkerSignals",
    tool_label: str,
    done: int,
    total: int,
    cancelled: bool,
) -> None:
    """Emit ``partial_results`` before the finish signal so the UI can show a cancel notice."""
    if not cancelled:
        return
    try:
        signals.partial_results.emit(tool_label, int(done), max(1, int(total)))
    except Exception:
        pass


class WorkerSignals(QObject):
    """Signals from background workers to the main window (single QObject for simple wiring)."""

    # --- Load + 2D render pipeline ---
    # mols_loaded: (batch, headers_or_empty, is_first_batch, is_last_batch)
    # batch entries are Chem.Mol (SDF/MOL) or dict[str,str] cell maps (text-first CSV/TSV).
    mols_loaded = Signal(list, list, bool, bool)
    # Emitted on the UI thread before bulk read when multiple structure columns exist; worker waits.
    structure_source_probe = Signal(list)
    # Last int: render_batch_session (0 = single / non-batch; non-zero must match app accept id)
    rendered = Signal(int, dict, bytes, bool, int, int, int)
    # Batch 2D render: (rows, render_batch_session) where rows are (oid, png, ok, w, h).
    # Batch renders never carry mol properties.
    rendered_batch = Signal(list, int)

    # --- Batch chemistry / tools (disconnect, descriptors, conformers, custom calc, export) ---
    disconnect_fragments_finished = Signal(list)
    neutralized = Signal(list)
    # Fast Prepare (fused disconnect, optional neutralize): list of
    # (oid, mol_blob_bytes, smaller_fragments_text, canonical_smiles_or_empty)
    fast_prepared = Signal(list)
    explicit_hydrogens_added = Signal(list)
    explicit_hydrogens_removed = Signal(list)
    calculated = Signal(list, list)
    # list of (oid, mol_or_None, confs_cell_json_str)
    conformers_finished = Signal(list)
    # list of (oid, mol_or_None, superpose_cell_str) — same packed format as ``confs`` when successful
    superpose_finished = Signal(list)
    # dict: ref_oid, geometry, results list of (oid, mol_or_None, meta)
    superpose_structures_finished = Signal(object)
    custom_calc = Signal(list)
    export_finished = Signal(str)
    # Core-based decomposition: list of (oid, {header: value}), then ordered new column names
    rgroup_decomp_finished = Signal(list, list)
    rgroup_decomp_failed = Signal(str)
    # BRICS / RECAP recomposition: product SMILES list, tool_title
    fragment_recomp_finished = Signal(list, str, int)
    fragment_recomp_failed = Signal(str, str)
    # BRICS / RECAP: (rows, headers, tool_title)
    fragment_decomp_finished = Signal(list, list, str)
    fragment_decomp_failed = Signal(str, str)
    # Reaction-based enumeration: ReactionEnumerationJobResult
    reaction_enum_finished = Signal(object)
    reaction_enum_failed = Signal(str, str)
    # Matched molecular pairs: (pairs, activity_column)
    mmp_finished = Signal(list, str)
    mmp_failed = Signal(str)
    # Activity cliff map: (pairs, activity_column, x_mode)
    activity_cliff_finished = Signal(list, str, str)
    activity_cliff_failed = Signal(str)
    # MMP pair neighborhood network: (pairs, activity_column)
    mmp_neighborhood_finished = Signal(list, str)
    mmp_neighborhood_failed = Signal(str)
    # SALI landscape: (points, activity_column, fp_choice, metric)
    sali_finished = Signal(list, str, str, str)
    sali_failed = Signal(str)
    cluster_failed = Signal(str)
    # Exploratory clustering: list of dict rows (method, params, settings, metrics, notes)
    cluster_explore_finished = Signal(list)
    # --- Progress banner (message, done, total; total < 0 => indeterminate) ---
    tool_progress = Signal(str, int, int)
    # Partial results were emitted before cancellation (tool_label, done, total).
    partial_results = Signal(str, int, int)


class FPSimilaritySignals(QObject):
    """Completion signals for :class:`FPSimilarityWorker` (owned by the dialog, not global WorkerSignals)."""

    finished = Signal(list)
    failed = Signal(str)


class PharmacophoreScreenSignals(QObject):
    """Completion signals for :class:`PharmacophoreScreenWorker` (owned by the dialog)."""

    finished = Signal(list)
    failed = Signal(str)


class DiverseSubsetSignals(QObject):
    """Completion signals for :class:`DiverseSubsetWorker` (owned by the dialog)."""

    # picked oids; column_rows; cached fp count; newly computed fp count
    finished = Signal(list, list, int, int)
    failed = Signal(str)


class BulkSimilaritySignals(QObject):
    """Completion signals for :class:`BulkSimilarityWorker` (owned by the dialog)."""

    finished = Signal(object)  # BulkSimilarityResult
    failed = Signal(str)


class SubstructureFilterSignals(QObject):
    """Completion signals for :class:`SubstructureFilterWorker` (owned by the main window)."""

    finished = Signal(int, object)  # job_gen, list[(smarts, structure_source, frozenset[oid])]
    failed = Signal(int, str)  # job_gen, message


class FilterApplySignals(QObject):
    """Completion signals for :class:`FilterApplyWorker` (owned by the main window)."""

    finished = Signal(int, object)  # job_gen, frozenset[int] of matched oids
    failed = Signal(int, str)  # job_gen, message


class SqliteRebuildSignals(QObject):
    """Completion signals for :class:`SqliteRebuildWorker` (owned by the main window)."""

    finished = Signal(int, str)  # job_gen, path to rebuilt sqlite file
    failed = Signal(int, str)  # job_gen, message
