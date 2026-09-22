# Join Columns

Join Columns concatenates two table columns into one new column with a delimiter you choose. Open from **Data → Table → Operations → Join Columns**.

## Goal

Combine two fields into a single cell for labels, export, or a later split.

## When to use

Use after import when a name, ID, or tag was stored in two columns and you want one joined value.

## Inputs / scope

Two text columns in the current table. Optional **Selected Rows Only**. The source columns are left unchanged.

## Options

- **First column** / **Second column** — left and right sides of the joined text.
- **Delimiter** — comma, comma+space, semicolon, tab, pipe, space, none (concatenate), or Custom.
- **Custom** — any string, including `\t` for a tab. Used when Delimiter is Custom.
- **New column** — output header. Defaults to `First_Second`. If the name already exists, a `(1)` suffix is added.
- **Skip empty cells** — if one side is blank, write the other value with no extra delimiter. Uncheck to always concatenate both sides.
- **Selected Rows Only** — write values only for the current selection; other rows stay empty in the new column.

## Workflow

1. Choose the two source columns (order is left then right).
2. Pick a delimiter (Custom for anything else).
3. Optionally set the new column name and row scope.
4. Apply and inspect the joined column.

## Use cases

- Join first and last name with a space.
- Combine an assay code and batch ID with an underscore.
- Build a `id, smiles` export field from two columns.

## Tips and limits

Skip empty is on by default so `"acid"` + blank does not become `"acid,"`. Uncheck it when you want a delimiter even for missing values. The original columns are not removed.
