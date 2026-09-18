# Prepare PDBQT

Prepare PDBQT builds receptor and/or ligand PDBQT files used by AutoDock-style engines such as Gnina.

## Goal

Convert prepared proteins and ligands into the charge/torsion representation docking expects.

## When to use

Use after Prepare PDB (receptor) and when ligands are ready as SDF, PDB, SMILES, or selected table rows.

## Inputs / scope

Receptor from **Input PDB**. Ligands from **SDF**, **PDB**, **SMILES**, or **Rows** (selected table structures). Only the active ligand input is shown.

## Options

- **Receptor:** **Input PDB**, **Output PDBQT**, **Generate PDBQT**.
- **Ligand:** **Input** (SDF / PDB / SMILES / Rows), matching file or SMILES / structure source, **Output PDBQT**, **Generate PDBQT**.
- **Close**.

## Workflow

1. Set receptor input PDB and PDBQT output, then **Generate PDBQT** in the Receptor box.
2. Choose ligand input (SDF, ligand PDB, SMILES, or selected rows) and **Generate PDBQT** in the Ligand box.
3. Point **Gnina…** at the resulting receptor and ligand files.

## Use cases

- Prepare a receptor once, then batch ligands from selected rows.
- Convert an SDF hit list or a ligand PDB to ligand PDBQT.
- Build files for a Gnina exhaustiveness sweep.

## Tips and limits

Ligand PDB should be a small-molecule file (HETATM), not a whole protein. Incomplete receptor residues (for example a truncated C-terminus left by PDBFixer) are skipped. Bad protonation or tautomers propagate into PDBQT — prep ligands chemically first. Selected-rows mode needs a valid structure source. Validate atom types if docking scores look nonsensical.
