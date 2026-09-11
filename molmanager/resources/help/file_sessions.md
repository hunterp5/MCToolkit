# Sessions

Sessions let you open, save, create, and duplicate MolManager project states so table data and related workspace context can be revisited later.

## Goal

Persist a working library and return to it without rebuilding filters, columns, and tool outputs from scratch.

## When to use

Use at natural breakpoints: after cleaning structures, before long QSAR runs, or when branching an experiment into a duplicate session.

## Inputs / scope

The current in-memory table and session metadata. Open loads from a saved session file; New starts clean; Duplicate copies the current state. Docked and floating plots (including custom pane titles), filters, and workspace layout are included.

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

Session files are not a substitute for raw data archives - keep original SDFs/CSVs. Opening a session redraws **Structure** images with the same auto Render 2D rules as opening a file (including the large-table skip limit). Column order, widths, hidden columns, sort, filters, workspace layout (including plot/table splitter positions), **docked plots**, and **floating plot windows** are restored: Plotter settings, PCA/t-SNE/UMAP/SOM embeddings, BOILED-Egg / Golden Triangle, SALI, Activity Cliff, and MMP Neighborhood maps (including pane layout, active page, and custom pane titles). Predict SOM maps (SMILES, sites, and atom scores) are stored so **SOM Map** images and the Predict SOM Browser can be restored on open. Successful Uni-pKa ionization ensembles are stored in the session so Protonate, Generate Protomers, LogD/LogS 7.4, CNS MPO, and AB-MPS can reuse them after Open / Duplicate without re-running inference. Failed predictions are not saved, so they can be retried. Opening replaces the current unsaved work unless you saved first.
