# Protein Viewer

Protein Viewer embeds the **Mol*** Viewer in Qt WebEngine so you can inspect a complex with Mol*’s own Components, Sequence, Measurements, Superposition, Interactions, and Density panels, then run mctoolkit prepare / dock / MD / pharmacophore tools around that canvas.

## Goal

Inspect a protein–ligand complex in 3D, restyle and measure it with Mol*, and run docking-ready preparation, Gnina, MD, MM-GBSA, or pharmacophore work without leaving mctoolkit.

## When to use

Use **Protein → Viewer** when you have a PDB, mmCIF, PDBQT, or similar coordinate file and want a Chimera/PyMOL-class look at the complex, plus SBDD tools.

## Inputs / scope

A structure file on disk. This tool does not read or write the compound table.

Supported text formats include PDB (`.pdb`, `.ent`), mmCIF (`.cif`, `.mmcif`, `.mcif`), PDBQT, and PQR. Other formats Mol* can draw (GRO, MOL2, SDF, XYZ) can be opened. Trajectory files (DCD, XTC, TRR) and maps (CCP4, MRC, MAP) open through **File → Open Trajectory…** / **Open Map…** and Mol*’s Structure / Density panels.

## Options

- **File → Open…** — add one or more structures (does not replace files already loaded). Mol* lists them under Structure / Components.
- **File → Save Structure…** — write the last loaded structure to disk as PDB or mmCIF, including atom and ligand-bond edits already applied.
- **File → Save to Session** — write structures plus a Mol* `molj` snapshot into the open mctoolkit session. **File → Session → Save Session** on the main window then writes that snapshot to disk.
- **File → Export Image…** — PNG of the Mol* canvas.
- **File → Open Trajectory…** — load DCD/XTC/TRR coordinates onto the current structure (Mol* trajectory controls). After **Tools → Simulate → Molecular Dynamics…**, the DCD is loaded automatically when present.
- **File → Open Map…** — load CCP4/MRC density; contour it in Mol* Density.
- **File → Close Structure** — clear loaded files from the canvas.
- **Log** — timestamped progress from Fast Prepare, PDBFixer, pdb2pqr, Minimize, MM-GBSA, MD, and Gnina under the canvas.
- **Mol* panels** — Sequence, Components (hide solvent, cartoon/sticks/surface, coloring, non-covalent interactions), Measurements (distance/angle/dihedral), Superposition, Density. Click a residue to focus it and show nearby contacts.
- **Tools → Pharmacophore** — **Editor**, **Screen Table…**, and **Open…**. Feature spheres overlay on the canvas while the editor is open.
- **Tools → Prepare → Fast Prepare…** — docking-ready cleanup for Gnina from the loaded structure or a PDB/mmCIF file. The prepared file is **overlaid**. The search box is shown with **View → Docking Box**.
- **Tools → Prepare → PDBFixer…** / **pdb2pqr…** / **Minimize…** / **Dock File…** — same as before; outputs overlay as extra structures.
- **Tools → Simulate → Dock Ligand** — PDBQT prepare, Gnina, Pose Browser. The pose browser docks in the side pane when this window is open. Browsing a pose overlays it in the pocket (magenta carbons in the pose file). **Add pose to Viewer** pins poses as extra structures.
- **Tools → Simulate → MM-GBSA…** / **Molecular Dynamics…** — score or run MD; last solute frame overlays. MD also writes a DCD, matching topology PDB, energy CSV, and sidecar JSON.
- **Tools → Simulate → Analyze Trajectory…** — RMSD / RMSF / energy (and ΔG when scored) vs time from that DCD. **Analyze…** on the MD dialog prefills paths. Overlay writes one solute frame; this is not a DCD player. See **Help → Analyze Trajectory**.
- **View → Docking Box** — Gnina search box from Prepare / Dock File.
- **View → Reset Camera** — Mol* camera reset.
- **Edit** — Undo/Redo, Edit Structure (two ligand atoms for Add/Delete Bond), Delete Atom(s). Rewrites the PDB/mmCIF then reloads Mol*. Use Mol* Components to hide chains; this window is not a chain Manager.

## Workflow

1. Choose **Protein → Viewer**.
2. **Open** one or more PDB or mmCIF files.
3. Use Mol* Components / Sequence / Measurements to inspect the fold and pocket (hide waters, show ligand sticks, add non-covalent interactions, click a ligand to focus surroundings).
4. Use **Tools → Prepare → Fast Prepare…** for a Gnina-ready receptor; compare the overlay with the original.
5. **Dock File…** or **Open Gnina…**, then browse poses. Add poses you want to keep.
6. Optional: **Open Trajectory…** or **Open Map…** for MD or ligand density.

## Use cases

- Check a receptor–ligand complex before docking prep.
- Run Fast Prepare / Minimize / MD / MM-GBSA and overlay results.
- Inspect docked poses next to the crystal ligand with Mol* contacts.
- Load a DCD from MD or a CCP4 map around the pocket.
