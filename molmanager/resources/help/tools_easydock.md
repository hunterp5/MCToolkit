# EasyDock

EasyDock docks table ligands: Meeko PDBQT preparation, then Smina or Vina into a receptor box. Best affinity is written to a score column; poses can be packed into **confs**. When the run finishes, poses open in a new interactive table with all Smina fields that were reported. A 3Dmol view on the left shows the selected pose inside the receptor; click a row to update the ligand. **View → Render** sets cartoon/surface/sticks for the receptor, ligand, and pocket residues. **View → Pocket View** draws nearby amino acids as ball-and-stick with residue labels and zooms to the ligand. Dragging the splitter resizes the canvas without resetting zoom.

## Goal

Screen selected (or all) table molecules against a prepared receptor without leaving the compound table.

## When to use

Use after **Prepare PDB** and **Prepare** have produced a receptor PDBQT, and ligands are protonated as you want them (this tool does not protonate).

## Inputs / scope

Table rows with valid structures; **Selected Rows Only** when checked. Receptor must be a rigid PDBQT.

## Options

- **Engine** - **Smina** (CLI; recommended on Windows) or **Vina** (EasyDock Python API; needs `pip install vina`).
- **Receptor** - PDBQT from Prepare.
- **Smina executable** - when Smina is selected.
- **Search box** - center and size in Å, or **Autobox** (Smina) with a **reference ligand** (PDB or PDBQT) and padding. Autobox uses one crystal/reference file for all table ligands.
- **Exhaustiveness**, **Num poses**, **Energy range** (Smina), **Seed**, **CPU threads**.
- **Score column** (default **Dock score**).
- **Write poses to confs column** - packed poses for View Conformers.
- **Save SDF** - optional multi-pose SDF.
- **Selected Rows Only**.

## Workflow

1. Clean the protein with **Prepare → Receptor PDB…** if needed.
2. Convert it with **Prepare → PDBQT…** to receptor PDBQT (if EasyDock is already open, the receptor path is filled in).
3. Protonate ligands separately if you need a pH-specific state.
4. Open **Tools → Dock → EasyDock…**, set the box and engine, run.
5. Inspect **Dock score** on the source table (kcal/mol, more negative is better) and the **results table** that opens with every pose and Smina field (affinity, RMSD, mode, …). The left pane shows the pose in the receptor.

## Use cases

- Dock a selected analogue series into a known pocket.
- Compare Smina scores after a Fast Prepare cleanup.
- Export docked poses to SDF for an external viewer.

## Tips and limits

Install **easydock** via the docking extra (`pip install -e ".[docking]"`). Smina is a separate binary (see README). Vina’s Python wheel is often unavailable on Windows — use Smina there. EasyDock does not prepare proteins and does not replace PDBFixer. Scores are vacuum AutoDock-family affinities, not experimental ΔG. Box placement dominates pose quality. Long jobs run in **Processes** and can be cancelled. Cite Minibaeva et al., *J. Cheminform.* 2023 and *J. Chem. Inf. Model.* 2026.
