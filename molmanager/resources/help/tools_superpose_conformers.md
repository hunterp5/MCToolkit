# Superpose Conformers

Superpose Conformers aligns conformers within a molecule for visual comparison using shared atoms and alignment options. When it finishes, a 3D results window opens in Superpose mode with per-conformer energies, ΔE, population, and RMSD.

## Goal

Overlay conformers so shape differences are easier to see in 3D.

## When to use

Use after generating ensembles when you want a common frame for inspection.

## Inputs / scope

Molecules that already have multiple conformers available in the working context; scope controls which rows are processed.

## Options

- Reference / source selectors as presented.
- **Heavy atoms only** - ignore hydrogens in alignment.
- **Allow reflection** - enantiomeric overlay option when enabled.
- **Max iterations** - alignment budget.
- **Align on** / pattern options when shown.
- **Selected Rows Only** - scope.

## Workflow

1. Generate or load multi-conformer molecules.
2. Open **Tools → Conformations → Superpose → Conformers…** and set alignment options.
3. Run superposition on the scoped rows.
4. Inspect the 3D results window (overlay plus energy table). If several rows were processed, the first overlay opens; use **View Conformers** on other **superpose** cells.

## Use cases

- Compare ring flip conformers of one ligand.
- Prepare aligned ensembles for a slide.
- Check whether RMS pruning left distinct poses.

## Tips and limits

Alignment quality depends on a common substructure. Flexible tails may still diverge after core overlay. This does not dock to a protein. If a **superpose** column already exists, new overlays go to **superpose (1)** (then **superpose (2)**, …) so the previous column is kept.
