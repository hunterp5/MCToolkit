# Plotter

Plotter builds interactive charts - scatter, histogram, 2D line, heatmap, box, violin, and radar - linked to table columns and selection.

## Goal

Visualize relationships and distributions to guide triage and communicate results.

## When to use

Use throughout analysis whenever a column relationship or distribution question is faster to see than to sort.

## Inputs / scope

Numeric (and categorical where supported) columns for rows in scope; **Selected Rows Only** limits points. Color-by columns optional.

## Options

- **Plot type** - **Scatter**, **Histogram**, **2D Line**, **Heatmap**, **Box plot**, **Violin**, **Radar**.
- Axes **X** / **Y** / **Z**, **Min** / **Max**, **Bin width** (and Y bin width).
- **Selected Rows Only**.
- **Color by**, **Spectrum**, color **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **Fit** - None / Linear / Quadratic / Normal / Truncated Normal / Log-Normal (plus trunc bounds when relevant).
- Radar: **Spokes**, **Entry** selectors.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. Choose plot type and map columns to axes/spokes.
2. Set scope, color-by, and ranges.
3. Plot and brush/select points as supported.
4. Dock or send to a new window for side-by-side work.

## Use cases

- Scatter potency vs LogP colored by cluster.
- Histogram a descriptor before slider filters.
- Radar-profile a few candidates across MPO inputs.

## Tips and limits

Huge point counts can be slow - use selection scope. Radar normalizes spokes and caps traces - read the on-dialog limits. Fits are exploratory, not hypothesis tests.
