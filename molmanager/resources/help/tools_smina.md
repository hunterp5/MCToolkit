# Smina

Smina runs the Smina docking engine with a receptor PDBQT, a ligand file, box center/size, and search settings. This is the file-based CLI; for table ligands and score writeback use **Tools → Dock → EasyDock…**.

## Goal

Dock prepared ligands into a receptor box and collect poses/scores from MolManager.

## When to use

Use when PDB/PDBQT receptor prep is done and you want local Smina runs without leaving the app.

## Inputs / scope

Requires a **Smina executable**, receptor PDBQT, ligand file, and an output path. Box defined by center and size, or **Autobox**.

## Options

- **Smina executable** - path to the binary.
- **Receptor**, **Ligand**, **Output** (+ **Browse...**). Receptor is PDBQT (Smina’s scoring grid). Ligand should be **SDF** (Browse also lists MOL/MOL2). PDBQT ligands are converted to SDF before docking so OpenBabel never has to guess bond orders. **Save as SDF** (on by default) sets Smina `--out` to SDF, so docked poses never go through PDBQT. Uncheck it only if you need PDBQT poses (that format cannot store double/aromatic bonds). Concatenated Meeko PDBQT is converted to one multi-mol SDF and docked in a **single** Smina process.
- **Autobox** - Smina `--autobox_ligand` plus **Padding** (`--autobox_add`, default 4 Å). Optional **Browse…** next to the checkbox sets a reference ligand (**PDB or PDBQT**); empty uses the docking ligand. Disables center/size.
- **Center X/Y/Z** and **Size X/Y/Z** - search box when autobox is off.
- **Exhaustiveness**, **Num modes**, **Energy range**.
- **Minimize Docked Poses** - after docking, run `smina --minimize` on all poses in one process. The SDF/PDBQT include both the **placement** pose and the **minimized** pose (`poseStage`).
- **CPU threads**, **Working dir**, **Extra args**.
- **Run Smina** / **Stop** / **Close**.

## Workflow

1. Set the Smina executable and working directory.
2. Choose receptor, ligand, and output paths.
3. Define the box (center/size, or **Autobox**) and search parameters.
4. **Run Smina**, monitor progress, **Stop** if needed. When the run finishes, poses open in a new interactive table (affinity, RMSD, mode, and other Smina fields when present). The left pane shows the selected pose in the receptor (click a row to switch). **View → Render** controls receptor, ligand, and pocket drawing styles. **View → Pocket View** labels nearby residues as ball-and-stick and zooms to the ligand. The SDF (or PDBQT) is also written to the output path. **Tools → Dock → Viewer** brings that results window back if you closed it.

## Use cases

- Redock a crystallographic ligand to validate the box.
- Dock a small selected series with higher exhaustiveness.
- Sweep energy range / num modes for pose diversity.

## Tips and limits

Docking quality hinges on box placement and ligand/receptor prep. Prefer an SDF ligand; PDBQT stores AutoDock types, not Kekulé orders, which is why OpenBabel `PerceiveBondOrders` warnings appear and aromatics become singles. Smina’s receptor must still be PDBQT. Smina must be installed and reachable. Long runs occupy CPU - adjust threads thoughtfully on shared machines.
