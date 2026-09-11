# Calculate Descriptors

Calculate Descriptors computes RDKit and related property columns (physicochemical, drug-likeness, counts, fingerprints, and more) into the table.

## Goal

Add numeric/text descriptor columns used by filters, plots, MPO, and models.

## When to use

Use after loading structures and before property-based triage, MPO scoring, or feature selection for QSAR.

## Inputs / scope

Rows with valid molecules in the chosen **Target Column** / structure source. Optional **Selected Rows Only** limits computation.

## Options

- **Target Column** - structure column to describe.
- **Selected Rows Only** - compute for the selection when checked.
- Category tabs / groups such as **Physiochemical**, **Name**, **Drug-likeness**, **Structural Counts**, **Ring Counts**, **Atom Counts**, **Complexity**, **Electronic**, **Fingerprints**.
- Per-descriptor checkboxes (e.g. LogP, Mol Weight, TPSA, QED, rule-of-five style flags).
- Confirm with **OK** to run (often as a background job).
- **QED Score**, **AB-MPS score**, and **CNS MPO score** columns are colored automatically (green = more favorable, through yellow, to red). QED uses 0–1, CNS MPO 0–6, and AB-MPS 0–14 (literature threshold) with worse values trending red. Change or clear this with the column header **Color** action.

## Workflow

1. Choose the structure **Target Column** and scope.
2. Open the category tabs and tick the descriptors you need.
3. Run the calculation and wait for **Processes** to finish.
4. Use new columns in filters, plots, or MPO/QSAR.

## Use cases

- Compute MW/LogP/TPSA for BOILED-Egg or Golden Triangle.
- Add drug-likeness flags before slider filtering.
- Generate fingerprint bit columns when a workflow expects them in-table.

## Tips and limits

LogD 7.4, LogS 7.4, CNS MPO, and AB-MPS use a Uni-pKa ionization ensemble when the pka extra is installed; otherwise they fall back to heuristics. Re-running a descriptor that already exists writes a new column (`Name (1)`, …) and leaves the original. Re-running ionization-dependent scores after switching from pkasolver is a new method, not a refresh. QED / AB-MPS / CNS MPO coloring uses fixed score ranges, not min/max of the current table.
