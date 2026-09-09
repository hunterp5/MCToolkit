# Predict SOM

Predict SOM runs FAME3R (via the NERDD service) to score atoms as likely **sites of metabolism** and draws a 2D map with those sites highlighted.

## Goal

See where a xenobiotic is most likely to be metabolized (Phase 1, Phase 2, or CYP-focused models) without leaving the table.

## When to use

Use after structures are loaded, when you need metabolic soft-spot maps for design, metabolite planning, or to compare substitution sites.

## Inputs / scope

Rows with valid molecules in the chosen structure **Source**, or a single **SMILES string**. Optional **Selected Rows Only**. Requires network access to NERDD.

## Options

- **Input** - table rows or a SMILES string.
- **Source** - structure column to read (table mode).
- **Selected Rows Only** - limit to the current selection.
- **Metabolism** - Phase 1 and 2 (default), Phase 1, Phase 2, or CYP-mediated.
- **SOM threshold** - probability cutoff for calling an atom a SOM (FAME3R default 0.30).
- **Compute FAME score** - optional applicability-domain score (slower).
- **Predict** - queue the background job.

## Workflow

1. Choose table rows or paste SMILES.
2. Pick the metabolism subset and threshold.
3. Run **Predict** and wait on **Processes**.
4. Review maps in the **Predict SOM Browser** (same layout as **File → Browser**: large structure preview, **← Back** / **Forward →**, optional property columns). Click an atom row to emphasize that atom on the map. Table columns **SOM Map**, **SOM Sites**, and **SOM Probabilities** are also written.

## Use cases

- Flag likely metabolic soft spots on a lead series.
- Compare Phase 1 vs Phase 2 maps for the same structure.
- Preview one SMILES before running the full table.

## Tips and limits

This is **not** Data → SOM (self-organizing map). Predictions use FAME3R models hosted on NERDD; they are free for non-commercial research. Highlighted atom indices match the preprocessed structure on the map. Failed molecules leave N/A text and no image. **Cancel** keeps completed molecules: they are written to the table and opened in the browser. Dock the browser with **Add to Main Window** if you want it beside the table.
