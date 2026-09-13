# Overview

MolManager is a desktop chemical table workspace for loading, preparing, analyzing, and exporting small-molecule data with RDKit-backed structure tools.

## Goal

Orient yourself in the main window so you can move between the compound table, filters/search, tools, charts, and background processes without losing context.

## When to use

Open this topic first when learning the app, after a layout change, or when you need a map of menus and workspace controls.

## Inputs / scope

Works on the current session table (structures plus property columns). Most tools can target all rows or only the current selection when **Selected Rows Only** is available.

## Options

- **File** - open/import data, sessions, export, selection browser.
- **Edit** - undo/redo, clipboard, and selection commands.
- **Tools** - prepare structures, fingerprints, docking helpers, design tools, predictors (pKa, permeability, SOM), random generators.
- **Protein** - 3D structure viewer for PDB, mmCIF, and related crystallographic files.
- **Data** - analyze table, plotter, dimensionality reduction, QSAR, MPO, medchem plots.
- **External** - SQL, PubChem, ChEMBL, patents.
- **Settings** - theme, fonts, hotkeys.
- **Help** - User Guide (this manual) and Citations (papers and licenses for external tools).
- **Layout** - rearrange or restore workspace panes.
- **Processes** - inspect running/queued background jobs.

## Workflow

1. Load or open a session with structures in the table.
2. Optionally filter or select the rows you care about.
3. Run a tool from **Tools** / **Data** / **External**; watch **Processes** for long jobs.
4. Inspect new columns, plots, or docked panes; export or save the session.

## Use cases

- Keep a working library open while clustering, scoring, and plotting subsets.
- Use the same session across docking prep, QSAR, and export without reloading files.
- Teach new users the menu map before diving into specialized dialogs.

## Tips and limits

Long jobs run in the background; cancel or clear them from **Processes**. Structure-dependent tools need a valid structure source column. Layout changes are session UI state - save the session if you want the table data preserved.
