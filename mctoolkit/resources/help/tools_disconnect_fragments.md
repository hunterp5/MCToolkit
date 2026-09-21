# Disconnect Fragments

Disconnect Fragments splits disconnected components into separate table rows so each fragment can be handled independently.

## Goal

Expand multi-component records (e.g. mixtures) into one row per fragment for downstream tools that expect single molecules.

## When to use

Use when SDFs contain salts/mixtures you want as separate entities, or before fragment-oriented enumeration workflows.

## Inputs / scope

Rows with multi-component structures in the chosen structure source; scope may include **Selected Rows Only**.

## Options

- Structure source selection.
- **Selected Rows Only** when available.
- Run action that writes additional rows for disconnected pieces.

## Workflow

1. Identify multi-component rows (or select them).
2. Run **Disconnect Fragments**.
3. Review new rows and original parents.
4. Optionally filter out unwanted ions.

## Use cases

- Separate ligand from crystallization additives in a row.
- Explode mixtures before diverse subset selection.
- Prepare single-component inputs for docking ligand prep.

## Tips and limits

Row count increases - plan filters afterward. Component identity/provenance columns may be limited; note origins manually if needed. Single-component rows are typically unchanged.
