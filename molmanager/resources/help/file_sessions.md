# Sessions

Sessions let you open, save, create, and duplicate MolManager project states so table data and related workspace context can be revisited later.

## Goal

Persist a working library and return to it without rebuilding filters, columns, and tool outputs from scratch.

## When to use

Use at natural breakpoints: after cleaning structures, before long QSAR runs, or when branching an experiment into a duplicate session.

## Inputs / scope

The current in-memory table and session metadata. Open loads from a saved session file; New starts clean; Duplicate copies the current state. Docked and floating plots (including custom pane titles), filters, workspace layout, and an open **Search** panel with its query rows are included.

## Options

- **Open** - load an existing session.
- **Save** / **Save As** - write the current session to disk.
- **New** - start a fresh session.
- **Duplicate** - clone the current session for parallel what-if work.

## Workflow

1. Build or import your table and optional tool columns.
2. **Save** the session with a clear name.
3. Later **Open** that session to resume.
4. **Duplicate** before risky bulk edits or alternate model settings.

## Use cases

- Checkpoint before protonation or fragment disconnection.
- Duplicate a parent library for separate MPO vs QSAR tracks.
- Hand a saved session to a collaborator with the same MolManager version.

## Tips and limits

Session files are not a substitute for raw data archives - keep original SDFs/CSVs. Opening a session keeps a full-workspace loading page up until rows, filters, Search, and plots are in place, then shows the table, plots, Search, and filter panel together. Auto **Render 2D** continues in the background after the workspace appears. **Structure** molecules are stored as compact RDKit binaries (plus SMILES) so Open does not re-parse SMILES; they are not rebuilt from **Protonated** or other tool columns. Filter min/max bounds are stored so slider cards restore without a full-table scan. Column order, widths, hidden columns, 2D pixmap chemistry columns, sort, filters, an active **Search** (panel visibility, columns, queries, AND/OR, and match options), workspace layout (including plot/table splitter positions), **docked plots**, and **floating plot windows** are restored: Plotter settings, PCA/t-SNE/UMAP/SOM embeddings, BOILED-Egg / Golden Triangle, SALI, Activity Cliff, and MMP Neighborhood maps (including pane layout, active page, and custom pane titles). Predict SOM maps (SMILES, sites, and atom scores) are stored so **SOM Map** images and the Predict SOM Browser can be restored on open. Successful Uni-pKa ionization ensembles are stored in the session so Protonate, Generate Protomers, LogD/LogS 7.4, CNS MPO, and AB-MPS can reuse them after Open / Duplicate without re-running inference. Failed predictions are not saved, so they can be retried. The last **MMP** run (matched pairs for the Transform Ledger) is stored so right-click **Transform Ledger** on MMP table columns works after Open / Duplicate. Large sessions restore rows, filters, plots, and tool sidecars in small steps so the window stays responsive. New saves use a compact columnar **version 2** `.cms` (gzipped JSON via orjson); older uncompressed version 1 sessions still open. Opening replaces the current unsaved work unless you saved first.
