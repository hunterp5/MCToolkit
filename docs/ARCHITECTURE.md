# MolManager architecture

Desktop chemistry table manager: **PyQt5** UI, **RDKit** structures, optional **PyTorch** tools (pKa, permeability).

## High-level layout

```mermaid
flowchart TB
  subgraph entry [Entry]
    app[molmanager.app:main]
  end
  subgraph window [Main window]
    CTA[ChemicalTableApp facade]
    PROG[ProgressController]
    SCOPE[ToolDialogScope]
    WRITE[TableWriteService]
    TS[TableSession]
    BUILD[TableBuildPipeline]
    SESS[SessionController]
    TOOLS[WorkspaceTools]
    CTM[CompoundTableModel]
    FPM[FilterProxyModel]
    PQ[ProcessQueueManager]
    HUB[BackgroundActivityHub]
  end
  subgraph data [Data]
    mols[MolStore]
    sqlite[SqliteTableStore]
  end
  subgraph workers [Workers]
    W[molmanager.workers.*]
  end
  app --> CTA
  CTA --> PROG
  CTA --> SCOPE
  CTA --> WRITE
  CTA --> TS
  CTA --> BUILD
  CTA --> SESS
  CTA --> TOOLS
  CTA --> CTM
  CTM --> FPM
  CTA --> PQ
  CTA --> HUB
  CTA --> mols
  CTA --> sqlite
  PQ --> W
  CTA --> W
```

## Main window (`molmanager/ui/main_window/`)

`ChemicalTableApp` is a **QMainWindow facade** over an explicit GUI-thread kernel
(`molmanager/ui/app_kernel.py`: `AppKernel`) and collaborators. Public methods stay on the
window as one-line forwards so dialogs and tests keep calling `app.on_calc_finished`,
`app._begin_tool_progress`, `app._selected_oids_set`, etc. Mixin files remain the
implementation bodies; they are **not** all on the window MRO.

| Collaborator | Module | Owns |
|--------------|--------|------|
| `ProgressController` | `ui/progress_controller.py` | Status chrome, `_begin_tool_progress` / `_finish_tool_progress` |
| `ToolDialogScope` | `ui/tool_dialog_scope.py` | Modeless tool dialogs, selected-rows-only scope, empty-selection abort |
| `TableWriteService` | `ui/table_write_service.py` | `on_calc_finished`, unique column names, `_ensure_columns` |
| `TableSession` | `ui/table_session.py` | Selection, chemistry-column lookup, sticky visible-row cache |
| `TableBuildPipeline` | `ui/table_build_pipeline.py` | Ingest chunks, SQLite rebuild, Render 2D batch/results (`QObject` child) |
| `SessionController` | `ui/session_controller.py` | `.cms` save/restore, table layout, session plots, legacy CSV |
| `WorkspaceTools` | `ui/workspace_tools.py` | Lazy cluster / dimred / QSAR / MPO / medchem adapters |
| `PlotDockHost` | `ui/plot_dock_host.py` | Dock/undock plot panes |
| `ProcessQueueManager` | `ui/process_queue.py` | Serial heavy tools |
| `BackgroundActivityHub` | `ui/background_activity.py` | Processes dialog |

New tools go through `ui/analysis_job_support.py` (which uses `tool_dialog_scope`) and kernel
methods — do not add mixin bases to `ChemicalTableApp`.

Remaining mixins on the window MRO are UI adapters that still talk to widgets directly
(`AppMenuMixin`, `TableUIMixin` edit/search/filters, structure-prep tools, MMP/SALI, dock,
predict, `GuiSettingsMixin`). Empty composition roots (`ChemistryMixin`, `SessionMixin`,
`IngestRenderMixin`, `PrepareStructuresMixin`, `ConformersDescriptorsMixin`,
`ToolsSqlPredictMixin`) are optional groupings only; they are **not** bases of
`ChemicalTableApp`.

`QMainWindow` precedes remaining mixins in the MRO, so Qt virtuals such as `closeEvent` must be declared on `ChemicalTableApp` (delegating into `AppLifecycleMixin`). Mixin implementations that need the C++ base should call `QMainWindow.closeEvent` explicitly rather than `super()`.

**Processes Cancel:** `BackgroundActivityHub.try_cancel_row` handles `background` jobs via `cancel_background_job()` when a cancel callable was registered with `register_background_job(..., cancel=…)`. Filter apply, substructure filter, dimred, and MedChem Space register cancel callables.

**Progress chrome (UX Phase 1):** Prepare-structure tools, QSAR train/predict, PDBFixer/PDBQT, dimred, and SQL load pages call `_begin_tool_progress` / `report_tool_progress` / `_finish_tool_progress`. Plot rebuilds register a short-lived Processes row (`Updating plot`) and set status to `Plot: collecting…` before series collect. Render 2D and auto-ingest 2D set status before task collection.

**SQL load:** `SqlLoadWorker` fetches rows and runs `MolFromSmiles` off the GUI thread; `ToolsSqlPredictMixin` applies prepared rows in budgeted `append_rows_batch` chunks. Cancellable via Processes (`register_background_job`).

**SQLite mirror rebuild:** GUI only chunk-exports cell text into memory; `SqliteRebuildWorker` streams inserts + oid index off the GUI (`Indexing table…` progress). Sync `_rebuild_sqlite_store_from_model` remains for tiny/test paths.

**Tool writeback:** `on_calc_finished` inserts columns immediately, then for large result sets chunks `apply_columns_values_bulk` / `set_column_text_by_oids` with `Writing results…` status; coloring and bounds run after the last chunk (`on_complete` for Protonate/fragment/SOM follow-ups). Fingerprint similarity uses the same chunked fill for large tables.

Tool mixins that remain on the window (structure prep, fragments, MMP/SALI, dock, predict) are thin adapters over `analysis_job_support` and the kernel. Ingest/render/sqlite live on `TableBuildPipeline`; column writeback on `TableWriteService`.

**Filter bounds:** bulk load/ingest calls `schedule_calculate_global_bounds()` (debounced); undo calls `calculate_global_bounds()` immediately when filter cards need fresh min/max. Session restore installs saved `global_bounds` when present and otherwise scans immediately.

## Table and visibility

- **Source of truth:** `CompoundTableModel` (`_rows`, OIDs, batched `dataChanged`) in
  `ui/compound_table_model.py`, composed from structure / bounds / bulk / color mixins.
- **View stack:** `ui/compound_table_view.py` (`CompoundTableView`, `StructureDelegate`,
  `CompoundTableHeaderView`); re-exported from `compound_table_model` for stable imports.
- **Helpers:** `services/numeric_bounds.py` (filter slider min/max scans);
  `column_color_compute.py` (gradient / categorical RGB).
- **Filtered view:** `FilterProxyModel` hides rows by OID set (`set_visible_oids`), not per-row `setRowHidden`.
- **Selection:** Qt selection + `_selected_oids_override` for large selections (tools/plots use `_selected_oids_set()`); logic lives in `TableSession` (`TableSelectionMixin` body).
- **SQLite mirror:** `SqliteTableStore` powers text/numeric filter pushdown and column search at 100k+ rows. Rebuilt in chunks on the GUI thread, then `SqliteRebuildWorker` builds the DB file.

## Background work

| Mechanism | Used for |
|-----------|----------|
| `ProcessQueueManager` | Serial heavy tools (descriptors, cluster, export, …) |
| `threadpool` | Substructure filter, dimred, MedChem space, SQLite export chunks |
| `_render_threadpool` | 2D structure rendering |
| `_background_jobs` + `BackgroundActivityHub` | **Processes** dialog rows for non-queue work |

Progress: `WorkerSignals.tool_progress` + `ToolProgressState` polling → bottom `status_label`.

## Plots and table sync

- **Plotter:** `ui/plot.py` (`PlotWidget`)
- **Dock host:** `ui/plot_dock_host.py` (`PlotDockHost`) owns dock/undock, panel width, and pane close; `PlotToolsMixin` delegates the public API
- **PCA / radar / dimred:** `ui/plotly_interactive_view.py`; dimred panel is `ui/dialogs/dimred_panel.py` (`DockableResultPlotPanel`), method dialogs stay in `ui/dialogs/dimensionality_reduction.py`
- **MedChem space:** `ui/dialogs/medchem_space.py` (`MedChemPlotPanel` also subclasses `DockableResultPlotPanel`)
- **Shared helpers:** `ui/plot_table_sync.py` (selection mapping, clear override); `ui/plotly_shell.py` + `ui/plotly_shell.html` (interactive Plotly HTML/JS for Plotter + Plotly views)
- **Result maps:** `ui/result_plot_panel.py` (`DockableResultPlotPanel`) is the shared dock chrome for SALI / MMP / cliffs / dimred / MedChem
- **Docked-plot chrome:** `ui/dockable_plot.py` re-exports glyphs, floating titles, footer buttons, and pane embed (`dockable_plot_glyphs.py`, `_title.py`, `_chrome.py`, `_embed.py`)
- **Workspace panes:** `ui/main_window/plot_pane.py` (`PlotPane`); `ui/main_window/workspace_layout.py` (`WorkspaceLayoutManager`)
- **Result browsers:** `ui/browsers/` (SOM, selection, MMP, SALI, metabolites) with shims at `ui/*_browser.py`
- **Filters:** `FilterPanelMixin` composes cards, apply, substructure, and bounds mixins under `ui/filters/` (`card_chrome.py` plus per-type card modules; `cards.py` is the barrel)
- **Conformer writeback:** `ui/main_window/conformer_writeback.py` (table append / packed ensemble / superpose mol lookup); `ConformersToolsMixin` stays the UI adapter
- **Table → plot:** debounced `_schedule_sync_active_plots_from_table_selection`
- **Plot → table:** `apply_table_selection_for_source_rows`
- **Filters / edits:** `_schedule_active_plots_replot` after filter apply; `dataChanged` on model for open plots
- **Substructure (large tables):** one or more SMARTS cards run via `SubstructureFilterWorker` off the GUI; sync/chunked apply consume override OID sets
- **UI workflow benchmark:** `scripts/benchmark_ui_workflows.py` times CSV load, `.cms` restore, filters, plot collect/replot, search, export
- **pKa / Uni-pKa benchmark:** `scripts/benchmark_pka.py` splits enumerate vs Uni-pKa MMFF/LMDB vs Uni-Mol infer and compares chunk sizes

## Adding a new Tool

1. Dialog under `molmanager/ui/dialogs/` (use `scope.selection_scope_checked`, `parent_app` on docked panels).
   Protein Prepare, Gnina dock, and Data Analysis live there; shims remain at the old `ui/`
   paths. Package `__init__` loads exports lazily so submodule imports do not pull Qt WebEngine.
2. Worker under `molmanager/workers/` if work is heavy.
3. Wire the menu action on `ChemicalTableApp` (thin forward to a collaborator or existing tool mixin). Do **not** add a new mixin base to the window class.
4. Long jobs: `process_queue.enqueue` + `_begin_tool_progress` / `report_tool_progress`.
5. Short threadpool jobs: `register_background_job` / `unregister_background_job`.
6. Tests under `tests/` (unit tests avoid full GUI where possible).

## Chemistry workers layout

Heavy chemistry jobs are split by concern (compat re-exports remain in `workers/chemistry_tools.py` and `workers/chemistry_conformers.py`):

| Module | Responsibility |
|--------|----------------|
| `workers/chemistry_descriptors.py` | Descriptor `CalcWorker` |
| `workers/conformer_generation.py` | Stochastic ETKDG conformer generation |
| `workers/superpose.py` | QRunnable adapters; re-exports geom/conformers/structures/RMSD |
| `workers/superpose_geom.py` | Ring maps, 2D depiction match, atom maps |
| `workers/superpose_conformers.py` | Align conformers of one molecule |
| `workers/superpose_structures.py` | Align distinct molecules onto a reference |
| `workers/superpose_rmsd.py` | Per-conformer RMSD |
| `workers/strain_energy.py` | Strain energy + overlay helpers |
| `workers/chemistry_calc.py` | Custom calculator (AST `safe_calc`) |
| `workers/chemistry_worker_common.py` | Shared progress throttling and force-field names |

Pure helpers live under `molmanager/services/` (e.g. `chemistry_columns.py`, `sql_load_policy.py`,
`table_scope.py`, `activity_records.py`, `table_selection.py`, `sqlite_text_match.py`,
`filter_config.py`, `column_labels.py`, `structure_grouping.py`). Domain modules must not import
`molmanager.ui`; Plotly legend cleanup lives in `molmanager/plotly_legend.py` (re-exported from
`ui/plotly_html.py`). Shared lineage header is `COLUMN_PARENT_OID` (`"Parent OID"`).
MMP / Activity Cliff / Pair Network / SALI share `ui/analysis_job_support.py` for scoped
activity-record prep, process-queue enqueue (`start_scoped_activity_job`), dialog open/finish
helpers (`ensure_activity_analysis_ready`, `finish_analysis_pairs`, `report_analysis_failure`).
Cluster / pKa / SOM / protomer / permeability reuse the same module for table readiness
(`ensure_table_ready_for_tool`), structure-scoped mol collect (`prepare_scoped_structure_mols`),
enqueue (`enqueue_process_queue_job` / `start_scoped_structure_job`), and cancellable failure
reporting (`report_cancellable_job_failure`). Mixins and dialogs stay thin adapters over those helpers.

Filter visibility changes invalidate a sticky `_visible_source_rows_cache` used by
plot replot (so debounced Plotter rebuilds do not rematerialize proxy maps per host).
`FilterProxyModel` is an explicit OID→row map (`QAbstractProxyModel`): `set_visible_oids`
rebuilds the accepted source-row list once instead of
`QSortFilterProxyModel.invalidateFilter` walking every row. `visible_source_rows()` seeds
the sticky cache without a `mapToSource` loop. Column insert/remove is forwarded 1:1
(`beginInsertColumns` / `beginRemoveColumns`) so the table view updates section count;
without that, deletes leave blank columns and new descriptor columns never appear.
When visibility does not change, finalize skips reset/replot.

Plotter axis/mode/histogram helpers live in `molmanager/plot_axes.py` (re-exported from
`ui/plot.py`). Series collection for scatter/histogram lives in `molmanager/plot_collect.py`.
Floating plot chrome is split into `ui/plot_bridge.py`, `ui/plot_statistics_panel.py`, and
`ui/plot_dialog.py`. Figure builders live in `ui/plot_render_mixin.py`; shell load/push and
table↔plot selection in `ui/plot_shell_mixin.py`; color/size/hover/fit in
`ui/plot_style_mixin.py`; axis/plot-type controls in `ui/plot_axis_mixin.py`; radar options in
`ui/plot_radar_mixin.py`; series collection in `ui/plot_collect_mixin.py`; session save/restore
in `ui/plot_session_mixin.py` (`PlotWidget` in `ui/plot.py` owns UI construction and orchestration).
Fingerprint session cache is an LRU capped by `fingerprint_cache_max_entries`
(`MOLMANAGER_FINGERPRINT_CACHE_MAX_ENTRIES`).

Ligand 3D viewer: `ui/mol_viewer_3d.py` re-exports. HTML/JS assembly is
`ui/mol_3d_html.py` (shared `assemble_3dmol_shell_page`), RDKit 2D/3D prep is
`ui/mol_3d_prepare.py`, Qt widgets are `ui/mol_3d_widget.py` (conformer nav + dock chrome mixins), and the floating
dialog/openers are `ui/mol_3d_dialog.py`. The sketcher embed is `ui/mol_3d_embed.py`;
strain-energy table fill is `ui/mol_3d_strain.py`. Protein viewer: `ui/protein_viewer.py`
re-exports; HTML is `ui/protein_viewer_html.py`, canvas is `ui/protein_embed.py`,
chain list is `ui/protein_chain_manager.py`. The window (`ui/protein_viewer_dialog.py`)
composes IO/session, render-style/H-bond, and sequence mixins.
Crystallographic inventory: `structure_components.py` re-exports types, CIF IO,
chain inventory, and atoms/pocket helpers.
`TableWriteService` owns descriptor/tool column writeback and unique header naming.
Structure-prep tools (protonate, Fast Prepare, disconnect/neutralize/explicit H) stay as
window mixins; Render 2D start/flush lives on `TableBuildPipeline` with ingest and SQLite rebuild.
Protein Prepare runtime: `workers/protein_prepare_runtime.py` orchestrates;
IO/residue maps are `protein_prepare_io.py`, pdb2pqr is `protein_prepare_pdb2pqr.py`,
AmberTools GAFF/GAFF2 (WSL on Windows) is `protein_prepare_amber.py`,
OpenMM min is `protein_prepare_minimize.py`. Complex-only Minimize (viewer **Minimize…**) is `protein_complex_minimize.py` with dialog `ui/dialogs/protein_minimize.py`. Tests patch names on the runtime module.

Gnina dock: `ui/dialogs/gnina_dock.py` is the widget. Argv, ligand files, and pose
I/O live in `gnina_job.py` (no Qt). `workers/gnina_dock_worker.py` owns the
`QProcess` and dock → optional crystal validation → optional minimize sequencing.
Launch/WSL/GPU probing stays in `gnina_launch.py`. Compat shims remain at
`ui/gnina_dock.py` / `ui/smina_dock.py`.

Auto Render 2D after ingest/session: the loading overlay stays until filter bounds
are ready and restored plot views have settled. Auto Structure renders start in the
background and do not block the workspace. Above `auto_render_2d_max_rows` auto 2D
is skipped. Lazy PNG store thresholds (`structure_render_lazy_*`) still control how
images are stored, not when the workspace appears. Session files store 2D mol
binaries and numeric filter bounds so Open can skip SMILES re-parse and a full
bounds scan.

## Related docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — coding standards, CI lint/headers, dependency audit
- [STEREO_AND_ISOMERISM.md](STEREO_AND_ISOMERISM.md)
- [VALENCE_BONDS_AND_AROMATICITY.md](VALENCE_BONDS_AND_AROMATICITY.md)
- [PACKAGING.md](PACKAGING.md)
