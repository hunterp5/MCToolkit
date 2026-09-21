# Generate Protomers

Generate Protomers enumerates protomers/tautomers from table rows or a SMILES string and can add chosen or all forms back into the table.

## Goal

Explore alternate ionization/tautomer forms explicitly as rows rather than a single dominant state.

## When to use

Use for tricky acidic/basic centers, tautomer-sensitive series, or when you want to dock or score multiple forms.

## Inputs / scope

**Input** mode is **Table rows** or **SMILES string**. Table mode uses **Source** and optional **Selected Rows Only**. **pH** influences Uni-pKa Boltzmann weights (same ensemble as Protonate / LogD).

## Options

- **Input** - Table rows / SMILES string.
- **Source** - structure column for table mode.
- **Selected Rows Only** - scope table inputs.
- **pH** - target pH for population weighting.
- **Generate** - enumerate forms. Results open in a browser (2D structure, form table, arrow keys) instead of filling the compound table.
- **Add current / selected / all to table** - write chosen forms from the browser. Added rows copy **pKa** from the parent ensemble. Source rows also get that shared column (same header as Predict pKa).

## Workflow

1. Choose input mode and structure source or SMILES.
2. Set **pH** and generate the ensemble.
3. Review enumerated structures in the protomer browser. Left/right arrows step through each form; only the current 2D depiction is drawn.
4. Add the current form, selected table rows, or all forms to the main table.

## Use cases

- Enumerate forms of a kinase hinge binder tautomer pair.
- Expand a single SMILES into candidates for docking.
- QA protonation hypotheses before QSAR on charged sets.

## Tips and limits

Enumeration can multiply row counts quickly - browse in the results window, then add only the forms you need. Weights are Uni-pKa Boltzmann populations at the chosen pH. Requires `unipkainfer`; treat outputs as candidates, not ground truth. Re-running after pkasolver is a new method, not a refresh. If Predict pKa already ran, the saved session restores the ensemble so Generate Protomers does not need another Uni-pKa pass.
