# Random Number

Random Number fills a column with draws from uniform continuous, uniform integer, or normal distributions, with optional seeding and clipping.

## Goal

Create stochastic helper columns for sampling, placeholders, or blinded splits.

## When to use

Use for quick random ranks, simulated noise columns, or reproducible sampling keys.

## Inputs / scope

Rows in scope (all or **Selected Rows Only**); writes the named column.

## Options

- **Column name** - output column.
- **Distribution** - Uniform continuous / Uniform integer / Normal.
- **Minimum**, **Maximum**, **Mean**, **Std. deviation** - as relevant.
- **Clip normal draws to min/max**.
- **Decimals**.
- **Use seed** / **Seed**.
- **Selected Rows Only**; **OK** / **Cancel**.

## Workflow

1. Open **Tools → Utilities → Random → Number**. Name the column and pick a distribution.
2. Set range or mean/sd (and clipping if normal).
3. Optionally set a seed for reproducibility.
4. Apply to all or selected rows.

## Use cases

- Assign random keys before a manual blind review.
- Simulate a noisy property for plot demos.
- Build a reproducible train/holdout key column.

## Tips and limits

Random columns are not experimental data - label them clearly. Seeds make repeats identical; omit seed for fresh draws. Integer vs continuous choice matters for downstream filters.
