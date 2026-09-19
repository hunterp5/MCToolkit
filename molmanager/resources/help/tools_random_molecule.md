# Random Molecule

Random Molecule fetches random catalog compounds into the table from **ChEMBL**, **PubChem**, or **ZINC**, with count, optional seed, and skip-existing.

## Goal

Populate a sandbox library for UI testing, method demos, or exploratory browsing.

## When to use

Use when you need quick structures without importing a file, or to pull random public-database examples.

## Inputs / scope

Adds new rows to the current table; does not require a pre-existing selection. Needs network access.

## Options

- **Source** - ChEMBL (default), PubChem, or ZINC.
- **Number of molecules**.
- **Seed (optional)** - reproducible catalog offsets for ChEMBL and PubChem; ZINC shuffles server-random ZINC22 pages.
- **Property filters** - optional min/max windows (leave **any** to ignore). Applied with RDKit on returned SMILES: **Heavy atoms**, **Nitrogen**, **Oxygen**, **Rotatable bonds**, **Rings**, **H-bond donors**, and **H-bond acceptors**. Sampling continues until the requested count matches.
- **Skip structures already in the table**.
- **Fetch from …** - retrieve SMILES plus database IDs (`ChEMBL_ID`, `CID`, or `ZINC_ID`, and a `Source` column). Matching rows also get count columns (`HeavyAtomCount`, `NitrogenCount`, …). Results open in a **Browser** (2D canvas + SMILES table; ← → to step).
- **Add to table** - in the results Browser, write the fetched molecules into the compound table.

## Workflow

1. Choose **Source**.
2. Set how many molecules to add.
3. Optionally set seed, property filters, and skip-existing.
4. **Fetch from …**. A Browser opens with 2D structures and a SMILES table; use the arrow keys to step through hits, then **Add to table**.

## Use cases

- Demo clustering on a fresh random set.
- Pull ChEMBL, PubChem, or ZINC samples for teaching fingerprints.
- Stress-test filters on diverse structures.

## Tips and limits

Random molecules are not project IP — do not confuse with your real series. Fetch needs network access and respects each database’s public API. ZINC uses the CartBlanche22 random job (ZINC15/ZINC20 REST is CAPTCHA-walled). Skipping existing structures helps avoid duplicates when re-running. At most 500 compounds per request. Tight property filters may fail if too few catalog pages contain matches — loosen a bound or retry.
