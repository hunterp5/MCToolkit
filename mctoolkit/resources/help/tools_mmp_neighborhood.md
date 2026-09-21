# Pair Network

Interactive neighborhood graph of matched molecular pairs. Open from the **MMP Transform Ledger** via **Pair Network** (uses the pairs currently shown in the ledger, including any reference filter).

## Goal

See how molecules connect through small structural changes, which neighbors improve or worsen activity, and which local series to grow next.

## When to use

Use after running **Data → MMP** when you want a landscape of the same MMP evidence.

## Inputs / scope

Pairs come from the open Transform Ledger (same activity column). Reference filtering on the ledger is respected.

## Workflow

1. Run **Data → MMP**, then click **Pair Network**.
2. Inspect the graph: **nodes** = molecules (default size = degree, color = activity); **edges** = MMP pairs (green Δ>0, red Δ<0).
3. Scroll to zoom; middle-mouse drag to pan; left-drag lasso / click to select.
4. Click a node to select it in the table; **Browse** opens the pair stepper for its edges. **Clear Selection** clears plot and table selection.
5. Optionally set **Neighborhood hops** > 0, select seed molecule(s) in the table, and click **Rebuild focus** to show only the local neighborhood.
6. Optional: **Add to Main Window** docks the plot beside the table. **Plot Options** sets **Color by** / **Size by** from table columns.

## Tips and limits

Pair Network does **not** use fingerprint chemical similarity. Edges are MMP relationships (shared core + different sidechains from fragmentation). Layout is a spring embedding of that graph. Large, dense graphs are harder to read — raise the minimum activity difference on the ledger run, set a maximum difference, restrict to selected rows, or use **Neighborhood hops**. Layout runs in the background; very large components use a faster sparse embedding. Edge Δ sign follows the stored pair orientation (OID order), not a reference molecule.
