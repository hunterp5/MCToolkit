# Tautomers

Tautomers enumerates likely connectivity tautomers (keto–enol, heterocycle NH shifts) from table rows or a SMILES string and can add chosen or all forms back into the table.

## Goal

Explore alternate tautomeric forms explicitly as rows rather than a single drawn structure.

## When to use

Use before docking or scoring when the drawn form might not be the bound tautomer (2-pyridone vs 2-hydroxypyridine, substituted imidazoles and pyrazoles, 1,3-dicarbonyls). For ionization / charge states at a pH, use **Generate Protomers** instead.

## Inputs / scope

**Input** mode is **Table rows** or **SMILES string**. Table mode uses **Source** and optional **Selected Rows Only**.

## Options

- **Input** - Table rows / SMILES string.
- **Source** - structure column for table mode.
- **Selected Rows Only** - scope table inputs.
- **Max tautomers** - cap per input structure (default 8). The input form is kept even if it would otherwise fall off the cap.
- **Generate** - enumerate forms. Results open in a browser (2D structure, form table, arrow keys) instead of filling the compound table.
- **Add current / selected / all to table** - write chosen forms from the browser with **Parent OID**, **Tautomer score**, and **Canonical tautomer**.

## Workflow

1. Choose input mode and structure source or SMILES.
2. Set **Max tautomers** if you need more than the default likely set.
3. Generate and review enumerated structures in the tautomer browser (higher RDKit tautomer score is preferred). Left/right arrows step through each form; only the current 2D depiction is drawn.
4. Add the current form, selected table rows, or all forms to the main table.

## Use cases

- Expand a kinase hinge binder into 2-pyridone and 2-hydroxypyridine before docking.
- List both NH tautomers of a 4-substituted imidazole.
- Check whether a series has any alternative tautomers at all.

## Tips and limits

Enumeration uses RDKit `TautomerEnumerator` (MolStandardize). Forms far below the best tautomer score (quinoid outliers, minor enols) are dropped. Unsubstituted imidazole/pyrazole often has only one unique SMILES. This tool does **not** change net charge; pair with Protonate / Generate Protomers for pH. Tautomerizing stereocenters may lose stereo (RDKit default). Adding every form to the table can multiply row counts — browse first, then add what you need.
