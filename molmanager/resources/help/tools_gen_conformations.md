# Generate Conformations

Generate Conformations builds 3D conformer ensembles per molecule with energy window, force field, and pruning controls, optionally writing to the table or SDF. When generation finishes, a 3D results window opens with per-conformer **E**, **ΔE vs ref**, **ΔE vs min**, **Pop. %**, and **RMSD**.

## Goal

Sample low-energy 3D shapes for inspection, strain-aware review, or export to external modeling tools.

## When to use

Use when you need multiple conformers (not just one pose), especially for flexible ligands or ensemble exports.

## Inputs / scope

Scoped rows with valid structures; **Selected Rows Only** when checked. Output may go to table and/or SDF file.

## Options

- **Conformers** - number to request.
- **Energy window** - keep conformers within this window.
- **Force field** - MMFF / UFF.
- **Seed** - reproducibility control.
- **RMS prune** - drop near-duplicates.
- **Max iterations** - minimizer budget.
- **Align on** - optional SMILES (or SMARTS) substructure used to overlay the ensemble after generation. Leave empty to keep embedder orientations.
- **Selected Rows Only** - scope.
- **Add to table** / **Save to SDF** (+ **Browse...**).

## Workflow

1. Select molecules and set ensemble size / energy window.
2. Choose force field, seed, RMS pruning, and optional **Align on** substructure.
3. Run generation (watch **Processes**).
4. Inspect the 3D results window: click a row to show that pose; check **Superpose** to overlay the ensemble, or **Selected Conformers** to overlay the table selection with a color legend. **View Conformers** on a packed cell reopens the same energy table. If several rows were processed, the window is the first ensemble; open the others from the table.
5. Optional: add results to the table and/or save SDF.

## Use cases

- Build ensembles for flexible linkers before manual review.
- Export multi-conformer SDF to an external docking suite.
- Compare conformer counts across a congeneric series.

## Tips and limits

Cost scales with atoms × conformers × rows. Force-field minima are not protein-aware. Failed embeddings skip or partially fill - check logs/status. Energies in the results window are vacuum molecular-mechanics totals (kcal/mol), not protein-bound or quantum-chemical values. The force field is the one chosen in this dialog (MMFF or UFF). Optional **Align on** overlays the ensemble on a common substructure; flexible tails may still diverge after core overlay.
