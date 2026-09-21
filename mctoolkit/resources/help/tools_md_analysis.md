# Analyze Trajectory

Compute RMSD, RMSF, and energy (plus optional MM-GBSA ΔG) from an OpenMM MD DCD. This is a plot/export tool, not a DCD player.

## Goal

Quantify how the protein and ligand moved during production: Cα RMSD vs frame 0, ligand RMSD after that Cα fit, ligand center-of-mass drift, per-residue Cα RMSF, and joined potential energy / ΔG vs time.

## When to use

Use after **Tools → Simulate → Molecular Dynamics…**. On finish, **Analyze…** fills the DCD, topology PDB, energy CSV, sidecar, and MM-GBSA CSV from that run. You can also open **Tools → Simulate → Analyze Trajectory…** and pick files from an older run.

## Inputs / scope

- **DCD** — production trajectory (includes TIP3P water when the MD was explicit).
- **Topology PDB** — full MD system in DCD atom order (`*_md_top.pdb`). The last-frame overlay CIF is solute-only and will not match an explicit DCD.
- **Sidecar** (`*.dcd.json`) — auto-fills topology, energy CSV, MM-GBSA CSV, timestep, DCD interval, solute atom count, and ligand residue keys. Resume writes a new DCD; the sidecar describes that DCD only.
- **Energy CSV** — `time_ps, E_pot_kcal` from the MD log interval.
- **MM-GBSA CSV** — optional; joined on nearest `time_ps`.

Solute atoms are sliced the same way snapshot MM-GBSA strips solvent (tleap water is appended).

## Options

- **Plots** — RMSD vs time (protein Cα and ligand), energy vs time, ΔG vs time when present, Cα RMSF vs residue.
- **Export CSV** — combined per-frame series; RMSF is written beside it as `*_rmsf.csv`.
- **Overlay selected frame** — write one solute PDB/CIF and overlay it like the MD last frame. This is not playback.

## Workflow

1. Run MD with a DCD path (topology, energy CSV, and sidecar are written automatically).
2. Open **Analyze Trajectory…** (or **Analyze…** on the MD dialog).
3. Confirm paths and click **Analyze**. Cancel from **Processes** if needed.
4. Inspect mean/max RMSD (and mean ΔG if scored). Export CSV if you want the table elsewhere.
5. Optionally overlay one frame on the canvas.

## Use cases

- Check that a short GB or TIP3P relaxation stayed near the starting pose.
- See whether the ligand drifted after Cα alignment.
- Join ΔG vs time with RMSD for one complex.

## Tips and limits

Cα fit is Kabsch to frame 0. RMSF is the square root of the mean-square Cα fluctuation about the fitted mean. Explicit DCDs include water; analysis uses the sidecar `solute_atoms` count so those waters are ignored. The 3D canvas is still a structure viewer — use **Overlay selected frame** for a snapshot, not a movie.
