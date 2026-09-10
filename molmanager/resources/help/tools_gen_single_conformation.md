# Generate Single Conformation

Generate Single Conformation embeds and minimizes one 3D conformer per scoped row for lightweight 3D coordinates.

## Goal

Obtain a single reasonable 3D structure per molecule without managing full ensembles.

## When to use

Use for quick 3D viewing, simple shape exports, or as a cheaper prelude to heavier conformer sampling.

## Inputs / scope

Valid structures in scope; **Selected Rows Only** optional.

## Options

- **Force field** - MMFF / UFF.
- **Seed** - random seed for embedding.
- **Max iterations** - minimization limit.
- **Selected Rows Only** - scope.
- Output options as shown (table/SDF depending on dialog).

## Workflow

1. Scope target rows.
2. Set force field, seed, and iteration limit.
3. Run the job.
4. Inspect the 3D results window (energy table plus pose). Reopen later with **View Conformers**.

## Use cases

- Quick 3D for a handful of leads.
- Provide coordinates required by an external tool.
- Standardize on one conformer before superposition tests.

## Tips and limits

One conformer may miss alternate basins - use Generate Conformations for coverage. Ring-rich or odd valences can fail embedding. Minimize compute by using selection scope.
