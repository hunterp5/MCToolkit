# UMAP

UMAP produces a nonlinear embedding often preserving more global structure than t-SNE, with n_neighbors and min_dist controls.

## Goal

Embed high-dimensional molecular/feature space into a 2D plot for visual structure of the library (UMAP).

## When to use

Use when tabular columns alone do not reveal groupings, or to compare chemical space coverage across subsets.

## Inputs / scope

Feature columns and/or fingerprints from a structure source; optional **Selected Rows Only**. Color-by column for overlays.

## Options

- **Features** - column list to include.
- **Fingerprint** - None or an FP type.
- **Structure from** - structure source when FP is used.
- **Selected Rows Only**.
- **Standardize features** - zero mean, unit variance.
- **Color by**, **Spectrum**, color **Min** / **Max**.
- **Size by**, marker **Min size** / **Max size** (pixels).
- **n_neighbors**, **min_dist**.
- **Max points**, **Random seed**.
- **Run UMAP**.
- Footer: gear (**Plot Options**), **Clear Selection**, then Add/Send glyph and **Close Plot** (pane **×** when docked).

## Workflow

1. Select feature columns and optional fingerprint.
2. Set standardization, color-by, and method parameters.
3. Run the embedding and inspect clusters/outliers.
4. Select points to highlight rows back in the table when linked.

## Use cases

- Color embeddings by activity or cluster labels.
- Compare selected series against the full library.
- Use FP-only embeddings when descriptors are incomplete.

## Tips and limits

Parameter changes alter tightness of clusters - tune deliberately. Requires the UMAP dependency where applicable. Subsampling via **Max points** affects rare chemotypes.
