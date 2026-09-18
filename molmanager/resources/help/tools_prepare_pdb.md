# Prepare PDB

Prepare PDB cleans and completes protein PDB files (heterogens, waters, missing atoms/hydrogens) ahead of docking setup.

## Goal

Produce a tidier receptor PDB suitable for PDBQT generation and docking.

## When to use

Use when raw PDB deposits need standard cleanup before Gnina or other docking.

## Inputs / scope

An input PDB path on disk; writes an output PDB path. Not a table-row tool.

## Options

- **Input PDB** / **Output PDB** with **Browse...**.
- **Remove heterogens...**
- **Keep crystallographic waters**
- **Replace non-standard residues...**
- **Add missing heavy atoms...**
- **Skip long missing stretches** + residue limit (default 8; skips N-terminal tags PDBFixer cannot place)
- **Add missing hydrogens at pH** + **pH**
- **Prepare PDB** / **Close**

## Workflow

1. Browse to the input PDB and set an output path.
2. Toggle cleanup options appropriate to your receptor.
3. Set hydrogen **pH** if adding hydrogens.
4. **Prepare PDB**, then continue to **Prepare → PDBQT…**.

## Use cases

- Clean a RCSB download before docking.
- Keep key waters in an active site.
- Add hydrogens at a chosen pH for protonation-sensitive pockets.

## Tips and limits

Automated fixes can mis-handle cofactors - inspect the site. This does not flex side chains for induced fit. Always visually check the binding pocket after prep. Protein Viewer **Prepare → Fast Prepare…** runs a fuller pipeline (pdb2pqr/PROPKA protein protonation, Uni-pKa ligand protomer at the same pH with optional pocket Coulomb reweight, and OpenMM GBn2 GBSA restrained minimization — protein-only AMBER by default, or GAFF/GAFF2 via AmberTools/WSL for the complex) on the structure already in the 3D canvas. **Prepare → PDBFixer…** is the in-viewer equivalent of this tool's repair/clean step without adding hydrogens.
