# Superpose Structures

Superpose Structures aligns structures across different rows, with SMARTS/MCS options when direct atom maps are not provided.

## Goal

Put related analogs into a common 3D frame for scaffold comparison.

## When to use

Use on a congeneric series after single-conformer or ensemble generation.

## Inputs / scope

Multiple rows with 3D (or embedable) structures; **Selected Rows Only** recommended for series focus.

## Options

- Reference index / **Source**.
- **Heavy atoms only**.
- **Allow reflection**.
- **Max iterations**.
- **Align on** / **SMARTS** pattern.
- **Use MCS when no pattern match** - fallback common substructure.
- **Selected Rows Only**.

## Workflow

1. Select the series and pick a reference row.
2. Open **Tools → Conformations → Superpose → Structures…**. Provide a SMARTS core or allow MCS fallback.
3. Run superposition.
4. Review the 3D results window (overlay plus energy table). Check **Selected Conformers** to highlight a subset.

## Use cases

- Overlay a matched pair series on a hinge core.
- Align R-group variants to a common scaffold.
- QA geometry before exporting a 3D SDF set.

## Tips and limits

MCS can be slow or ambiguous on distant analogs. Poor SMARTS yields wrong overlays - test on two rows first. 2D-only molecules need conformer generation first. If a **superpose** column already exists, new overlays go to **superpose (1)** (then **superpose (2)**, …) so the previous column is kept.
