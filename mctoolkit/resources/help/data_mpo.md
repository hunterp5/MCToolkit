# MPO Scoring

MPO Scoring combines multiple property desirability functions into a single multi-parameter score using arithmetic or geometric mean aggregation.

## Goal

Rank compounds by simultaneous fitness across several numeric criteria (e.g. potency + MW + LogP).

## When to use

Use during multiparameter optimization when single-column sorting hides tradeoffs.

## Inputs / scope

Numeric property columns already in the table; optional **Selected Rows Only**. Desirability curves are defined per criterion.

## Options

- **Output column** - combined MPO score name.
- **Combine** - **Arithmetic mean** / **Geometric mean**.
- **Also write per-property desirability columns**.
- **Decimals** - display/rounding.
- Property criteria list with **Add** / **Remove**.
- Per criterion: **Function** (Linear / Gaussian / Step), **Goal** (Maximize / Minimize / Target / range), **Low**, **High**, **Target**, **Center**, **Sigma**, **Weight**.
- **Selected Rows Only**; **OK** / **Cancel**.

## Workflow

1. Add criteria for each property and set function/goal/limits.
2. Choose combine mode and output column name.
3. Optionally write per-property desirability columns.
4. Run and sort/filter by the MPO score.

## Use cases

- Balance potency against MW and TPSA.
- Target a LogP window with a Gaussian desirability.
- Weight safety-related properties higher than nicer-to-have ones.

## Tips and limits

Garbage properties in → misleading MPO out; compute descriptors first. Geometric mean punishes any near-zero desirability strongly. Tune weights intentionally; equal weights are not always appropriate.
