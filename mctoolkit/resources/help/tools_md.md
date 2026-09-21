# Molecular Dynamics

Run Langevin MD on a protein–ligand complex: implicit GBSA (GBn2/OBC2) or a TIP3P water box (PME, NPT). Optionally score 1-trajectory MM-GBSA on production snapshots.

## Goal

Relax a holo pose with thermal dynamics and, if enabled, average MM-GBSA over snapshots. Implicit GB is the fast ranking path. TIP3P is the physically better solvent model; it is also much slower.

## When to use

Use after the complex is prepared and protonated. Prefer a GPU OpenMM platform (CUDA or OpenCL). CPU GBSA and CPU explicit water are both slow.

## Inputs / scope

A Manager structure or PDB/mmCIF in Protein Viewer, with ligand chemistry for GAFF/GAFF2. Default implicit protocol: minimize, 10 ps restrained eq, 100 ps production, MM-GBSA every 10 ps.

## Options

- **Solvation** — GBn2 (default), OBC2, or **TIP3P box (PME, NPT)**. TIP3P uses tleap `solvateBox` plus NaCl, then OpenMM PME and a Monte Carlo barostat.
- **Box padding** — Å around the solute for TIP3P (default 10). Ignored for GBSA.
- **Salt** — GB Debye screening, or NaCl concentration for tleap ions.
- **Equilibration / production** — times in ps. Keep production modest unless you have a GPU.
- **Eq. restraint k** — backbone+ligand heavy atoms by default; **Prod. restraint k** 0 turns restraints off in production.
- **Checkpoint** — OpenMM `.chk` written during production. **Resume from checkpoint** skips minimize/eq and continues remaining production. Resume starts a new DCD.
- **Score MM-GBSA on production snapshots** — writes a report and CSV of ΔG vs time. For TIP3P, water and ions are stripped first; scoring is still GBn2 on the dry complex.
- **Trajectory DCD** — OpenMM DCD of production frames (includes water for TIP3P). Protein Viewer overlays the **last solute frame**, not the DCD.

## Workflow

1. Prepare the holo complex.
2. Open **Tools → Simulate → Molecular Dynamics…**.
3. Choose GBSA or TIP3P, set production length, and whether to score MM-GBSA.
4. **Run MD**. Cancel from **Processes** if needed; a checkpoint lets you resume.
5. Inspect the last-frame overlay and the MM-GBSA mean ± SD when scoring was on.

## Use cases

- Short GB relaxation of a docked pose before ranking.
- Short explicit-solvent NPT of one complex (not a library screen).
- A ΔG vs time table for one complex.

## Tips and limits

This is not FEP and does not replace multi-ns production MD. Entropy is omitted. The pip OpenMM wheel includes OpenCL, not CUDA. AmberTools is required (WSL on Windows). A 10 Å TIP3P box is tens of thousands of atoms; start with 10–100 ps.
