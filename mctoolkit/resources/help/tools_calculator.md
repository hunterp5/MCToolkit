# Calculator

Calculator creates a new numeric column from a math expression over existing numeric columns, with a keypad and clickable column variables.

## Goal

Derive simple scores, unit conversions, or combined metrics without exporting to a spreadsheet.

## When to use

Use for quick ligand-efficiency style ratios, log transforms you define, or combining assay replicates already in the table.

## Inputs / scope

Numeric columns in the table; expression applies to all rows or **Selected Rows Only**.

## Options

- **Expression** field - formula using `[ColumnName]` variables.
- Keypad - digits/operators, **√**, **log**, **exp**, **π**, parentheses, clear/backspace.
- **Column variables** - tap a column to insert `[ColumnName]`.
- **Column name** - output column to write.
- **Selected Rows Only** - limit evaluation scope.
- **Apply to Table** - compute and write values.

## Workflow

1. Open **Tools → Utilities → Calculator** and set the output **Column name**.
2. Build an expression via keypad and column variable buttons.
3. Choose scope (**Selected Rows Only** or all).
4. **Apply to Table** and spot-check results.

## Use cases

- Compute a composite score from potency and MW.
- Convert nM to pIC50-style values with a defined expression.
- Fill a helper column used later in MPO.

## Tips and limits

Non-numeric or missing inputs yield empty/invalid results for that row. Expression errors should be fixed before relying on the column. This is not a full algebra system - keep formulas simple and explicit.
