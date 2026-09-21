# MM-GBSA

Score a prepared protein–ligand complex with 1-trajectory MM-GBSA in OpenMM (GBn2 or OBC2).

## Goal

Rank a docked or crystal pose with an implicit-solvent MM energy: ΔG ≈ E_complex − E_receptor − E_ligand (kcal/mol). Entropy (−TΔS) is omitted. This is a ranking score, not an experimental binding free energy.

## When to use

Use after **Tools → Prepare → Fast Prepare…** or **Minimize…** on a holo structure (GAFF2 ligand chemistry available). Do not use on apo protein.

## Inputs / scope

A Manager structure or PDB/mmCIF file in Protein Viewer. Needs a ligand plus SMILES, SDF/MOL2, or mmCIF `_chem_comp_bond` so AmberTools can assign GAFF/GAFF2 types. Waters are stripped by default.

## Options

- **Ligand force field** — GAFF2 (default) or GAFF via AmberTools (WSL on Windows).
- **Solvation** — GBn2 (default) or OBC2. Salt (default 0.15 M) sets GB Debye screening.
- **Minimize complex before scoring** — restrained OpenMM min, then score the relaxed coordinates (recommended).
- **Keep waters** — off by default (standard MM-GBSA). On includes crystal waters in the receptor.

## Workflow

1. Prepare and protonate the complex (Fast Prepare or pdb2pqr + Minimize).
2. Open **Tools → Simulate → MM-GBSA…**.
3. Confirm ligand chemistry (SMILES / SDF / mmCIF bonds).
4. **Score**. Watch the Protein Viewer log and **Processes**.
5. Read the report table (COMPLEX / RECEPTOR / LIGAND / DELTA). Overlay the minimized complex if that output was set.

## Use cases

- Rescore a Gnina pose after OpenMM relaxation.
- Compare two ligands in the same pocket with the same GB protocol.

## Tips and limits

1-trajectory bonded Δ should be near zero; large bonded Δ means atom mapping is wrong. Numbers depend on GB model, salt, and whether you minimized. Implicit solvent is not a water box. Needs the docking extra (`openmm`) and AmberTools.
