# Open File

Open File loads a molecule or data file into a new or current workspace table (SDF, MOL, SMILES, CSV/TSV-style tables, and related formats).

## Goal

Bring an external library into MolManager as the working compound table with structures and properties ready for tools.

## When to use

Start a new analysis from disk, replace the current table with a fresh file, or reload a cleaned export.

## Inputs / scope

File on disk. Structure columns are parsed when the format carries molecules; CSV/TSV-style tables with a SMILES or structure column (comma, semicolon, tab, or pipe).

## Options

- **File browser** / path selection for supported chemistry and table formats (SDF, MOL, SMILES, CSV/TSV-style).
- **Format parsing** - multi-molecule SDF, SMILES lists, and delimited tables with structure columns.
- **Main table** columns and depictions populated after a successful load.

## Workflow

1. Choose **File → Open** (or equivalent) and select a file.
2. Confirm the table populated with expected columns and depictions.
3. Fix structure source if needed, then filter or run tools.
4. Save a session if you will continue later.

## Use cases

- Load an HTS SDF for clustering and diverse subset picking.
- Open a CSV of SMILES plus assay columns for QSAR.
- Reload a vendor catalog before fingerprint similarity searches.

## Tips and limits

Very large files may take time and memory; prefer filtered exports when possible. Malformed SMILES rows may appear empty or invalid for structure tools. Opening typically replaces or defines the working table - use Import when you need to append. A loading page stays up until the table is built and auto **Render 2D** finishes (skipped when the row count is over the auto-2D limit). CSV/TSV tables may use comma, semicolon (common for ChEMBL downloads), tab, or pipe; the delimiter is detected from the header.
