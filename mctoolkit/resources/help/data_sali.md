# SALI

Plot pairwise fingerprint similarity against absolute activity difference, colored by the Structure–Activity Landscape Index. Open from **Data → SALI**.

## Goal

Find activity cliffs and flat SAR regions: pairs that are structurally similar but differ sharply in activity (high SALI), versus similar pairs with quiet Δactivity.

## When to use

Use on a series with a meaningful activity column when you want a fingerprint-based landscape (not MMP fragment pairs). Prefer selected rows or a similarity floor on large tables.

## Inputs / scope

Structures from **Molecules from**; **Activity column** for Δactivity. Scope via **Selected Rows Only**.

## Options

- **Molecules from** - structure source.
- **Activity column** - property for deltas and SALI.
- **Fingerprint** / **Similarity metric** - chemical similarity (Tanimoto recommended).
- **Minimum similarity** - drop distant pairs (default 0.30).
- **Minimum activity difference** - drop weak deltas.
- **Max pairs to plot** - keep the highest-SALI pairs when many qualify.
- **Selected Rows Only**.

## Workflow

1. Select or filter to a relevant chemical space.
2. Choose activity column, fingerprint, and filters.
3. Run the tool. Results open in an interactive map: **X** = similarity, **Y** = |Δactivity|, **color** = SALI = |Δ| / (1 − similarity) by default.
4. Click a point to select both molecules in the table. **Browse** opens a side-by-side pair browser (step through plot pairs with ←/→; **Selected Only** limits to pairs involving the table selection). **Clear Selection** clears plot and table selection.
5. Optional: **Add to Main Window** docks the plot beside the table. **Plot Options** sets **Color by** / **Size by** (table columns; pair points use the mean of both molecules when numeric).

## Use cases

- Spot potency cliffs among near-neighbors.
- Compare landscapes across fingerprint types.
- Restrict to high similarity to focus on local SAR.

## Tips and limits

Pairwise cost is O(n²) in molecule count—raise minimum similarity, lower max pairs, or use Selected Rows Only on large sets. **Max pairs** keeps a bounded top-SALI set during the scan so the plot does not materialize every qualifying pair. Near-identical structures (similarity ≈ 1) use a small denominator floor so SALI stays finite. Not a substitute for MMP transform mining or full QSAR.
