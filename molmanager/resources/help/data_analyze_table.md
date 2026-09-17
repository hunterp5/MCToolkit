# Statistics

Statistics computes summary statistics for table columns so you can inspect distributions and data quality quickly. Open from **Data → Table → Statistics**.

## Goal

Understand column coverage, central tendency, and spread before modeling or filtering.

## When to use

Use after import, after descriptor calculation, or when diagnosing outliers.

## Inputs / scope

Columns in the current table; may respect current visibility/selection depending on the analyzer UI.

## Options

- **Columns** - selection or automatic inclusion of analyzable columns.
- **Summary statistics** - counts, mean/min/max, and related measures as provided.
- **Refresh** - recompute after the table changes.

## Workflow

1. Ensure the columns of interest exist and are populated.
2. Open **Data → Table → Statistics**.
3. Review summaries for missingness and outliers.
4. Follow up with filters or plots on suspicious columns.

## Use cases

- Check descriptor coverage after a partial selection run.
- Spot assay columns with many empties before QSAR.
- Compare spreads of related score columns.

## Tips and limits

Statistics are descriptive only. Non-numeric columns have limited summaries. Re-run after major filters if you need stats on the visible subset specifically.
