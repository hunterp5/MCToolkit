# Activity Cliffs

Plot matched molecular pairs as an activity-cliff scatter: structural-change size versus absolute activity difference. Open from the **MMP Transform Ledger** via **Activity Cliffs** (uses the pairs currently shown in the ledger, including any reference filter).

## Goal

See which small structural changes produce large activity shifts (cliffs) versus quiet SAR, then drill into the underlying pair.

## When to use

Use after running **Data → MMP** when you want a landscape view of the same MMP evidence.

## Inputs / scope

Pairs come from the open Transform Ledger (same activity column). Reference filtering on the ledger is respected.

## Options (in the map)

- **X axis** - changing heavy atoms (default) or fragment fingerprint distance (1 − Tanimoto); set under **Plot Options**.
- **Color by** / **Size by** - optional table columns (**Plot Options**). Default color is signed Δ. For pair points, numeric columns use the mean of both molecules.

## Workflow

1. Run **Data → MMP** with the desired cuts, variable-atom cap, and min/max activity difference.
2. Optionally set a reference molecule on the ledger.
3. Click **Activity Cliffs**. Results open in an interactive cliff map (color = signed Δ).
4. Click a point to select both molecules in the table; **Browse** opens the MMP pair browser for that cliff. **Clear Selection** clears plot and table selection.
5. Optional: **Add to Main Window** docks the plot beside the table.

## Use cases

- Spot potency cliffs from halogen or alkyl swaps.
- Separate large-|Δ| outliers from dense low-impact changes.
- Switch X axis to fragment distance when heavy-atom counts pile up.

## Tips and limits

Same MMP caveats as the transform ledger: cut settings and activity noise matter. Points can overlap on integer heavy-atom X values (light jitter is applied). Not a substitute for full QSAR on diverse libraries.
