# Split Column

Split Column takes one table column whose cells contain several values (comma, tab, space, semicolon, pipe, or a custom character) and writes each field into its own new column. Open from **Data → Table → Split Column**.

## Goal

Turn packed lists in a single cell into separate columns for filtering, plotting, and export.

## When to use

Use after import when a field arrived as a joined list (synonyms, flags, assay codes, author lists).

## Inputs / scope

One text column in the current table. Optional **Selected Rows Only**. The original column is left unchanged.

## Options

- **Column** — source cells to split.
- **Separator** — Auto (comma, semicolon, tab, or pipe when present; otherwise whitespace), or an explicit delimiter, or Custom.
- **Prefix** — new headers are `Prefix_1`, `Prefix_2`, …. Defaults to the source column name. If a name already exists, a `(1)` suffix is added. With **Only Split Largest/Smallest Value**, a single column named with this prefix is written.
- **Only Split Largest Value** — keep only the largest numeric field from each cell (one new column). Unchecks the smallest option.
- **Only Split Smallest Value** — keep only the smallest numeric field from each cell (one new column). Unchecks the largest option.
- **Selected Rows Only** — write values only for the current selection; other rows stay empty in the new columns.

## Workflow

1. Select the packed column.
2. Confirm the separator (Auto is usually enough).
3. Optionally set a prefix and row scope.
4. Apply and inspect the new columns.

## Use cases

- Split `tag1, tag2, tag3` into three flag columns.
- Expand a tab-separated vendor ID list.
- Break a semicolon-delimited synonym field before text filters.

## Tips and limits

Quoted CSV-style fields (`"a, b", c`) stay as one value when the separator is comma, semicolon, tab, or pipe. Space mode collapses runs of whitespace. At most 256 fields per cell are kept. Empty source cells leave the new columns blank for that row. Largest/smallest prefer numbers; if a cell has no numeric fields, the last/first non-empty token in sort order is used.
