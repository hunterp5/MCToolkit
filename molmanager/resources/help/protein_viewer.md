# Protein Viewer

Protein Viewer loads a crystallographic structure into an interactive 3Dmol.js canvas and lists each PDB chain (protein, ligands, metals, and solvent on that chain ID) in a Manager panel.

## Goal

Inspect a protein (and associated ligands, cofactors, metals, and waters) in 3D, then hide, select, restyle, or delete individual chains without leaving MolManager.

## When to use

Use **Protein → Viewer** when you have a PDB, mmCIF, PDBQT, or similar coordinate file and want a Chimera/PyMOL-style look at the complex.

## Inputs / scope

A structure file on disk. This tool does not read or write the compound table.

Supported text formats include PDB (`.pdb`, `.ent`), mmCIF (`.cif`, `.mmcif`, `.mcif`), PDBQT, and PQR. Other 3D formats that 3Dmol.js can draw (GRO, MOL2, SDF, XYZ) can be opened; chain splitting is richest for PDB and mmCIF. When mmCIF includes `_chem_comp_bond`, stick and ball-and-stick styles draw double and triple bonds from that table (3Dmol's built-in CIF parser does not).

## Options

- **File → Open…** — add one or more structures to this session (does not replace files already loaded).
- **File → Save Structure…** — write the Manager-selected structure (or the last loaded file) to disk as PDB or mmCIF, including Sequence edits already applied in the viewer.
- **Manager** — each file is a top-level group named after the file. Under that, components are grouped by the **PDB chain ID** written in the coordinate file (protein, ligands, metals, and waters of chain A stay under Chain A; a ligand recorded as chain L is its own Chain L group). Click a row (or an atom in 3D) to select it; the checkbox hides or shows that chain.
- **Sequence** — editable sequence of every chain, including amino acids, **lowercase letters for residues missing from the coordinates** (SEQRES / `_pdbx_poly_seq_scheme` gaps), ligands/cofactors (`+`), metals (`*`), and waters (`~`); selected observed characters highlight in 3D.
- **Prepare…** — docking-ready cleanup: PDBFixer repair, pdb2pqr/PROPKA protein protonation at a chosen pH (ligand stays in for holo titration), Uni-pKa ligand protomer at that pH with optional pocket Coulomb reweight (SMILES/SDF, or mmCIF `_chem_comp_bond`), optional Manager-selected or ligand-near waters, then optional OpenMM restrained minimization. **Keep ligand in prepared mmCIF** is on by default; **Restrained minimization** is off until you check it. You choose **protein force field** (ff14SB or ff99SB-ILDN), **ligand force field** (GAFF2 or OpenFF Sage), **solvation** (GBn2 GBSA, OBC2, or vacuum), salt, and whether to restrain **backbone**, **Cα**, or **backbone plus ligand**. Highest-occupancy altlocs are kept; SEQRES gaps are modeled with PDBFixer (not only PDBFixer's residue-number alignment, which misses tagged N-termini and kinase inserts). SEQRES loops next to the ligand can still be skipped. Output remarks include pocket HIS/ASP/GLU names and Cα/pocket RMSD vs the start of minimization. Default output is **mmCIF** (PDB is optional) so ligand bond orders are written as `_chem_comp_bond`. **mmCIF inputs stay mmCIF for the whole Prepare run**. pdb2pqr still uses a PDB/PQR scratch file internally (PQR is the format that carries per-atom charges); that is converted back immediately so HID/HIE/HIP, ASH, GLH names, hydrogens, and ligand bonds survive in the mmCIF. Per-atom pdb2pqr charges are not stored in standard mmCIF/`ATOM` records — keep the scratch `.pqr` if you need them for APBS. PDBQT is a docking export, not the archival protonation file. The result is **overlaid** on the original instead of replacing it.
- **Checkbox** — hide or show a chain.
- **Click** a Manager row (or an atom in 3D) — select that chain and highlight it.
- **Select → Hide** / **Show** — apply visibility to the current Manager selection.
- **Select → Focus** (or double-click a row) — zoom the camera to the selection.
- **Select → Delete** (or Delete/Backspace) — remove selected chains from the viewer.
- **Select → Render** — cartoon, surface, sticks, ball and stick, spheres, or wireframe for the selection only.
- **Select → Color** — tint carbons (non-heteroatoms) in the selection; N, O, S, and other heteroatoms stay CPK. **Custom…** opens a color picker.
- **File → Close Structure** — clear the canvas.
- **View → Render → Protein** / **Ligand** — set cartoon, surface, sticks, ball and stick, spheres, or wireframe for every protein chain or every ligand independently. **Color** tints carbons (and the protein cartoon) while leaving heteroatoms in CPK colors (N blue, O red, S yellow).
- **View → Hydrogens → All** / **Polar** — control explicit hydrogens on the 3D canvas. **Polar** (default) hides carbon-bound hydrogens and keeps those bonded to N, O, S, or F. **All** shows every explicit hydrogen.
- **View → Hydrogen Bonds → Protein** / **Ligand** / **Protein–Ligand** — draw dashed hydrogen bonds on the canvas. **Protein** (gold) is intramolecular within protein chains, **Ligand** (cyan) is intramolecular within ligands, and **Protein–Ligand** (green) is intermolecular between protein and ligand. Geometry uses explicit polar hydrogens when the file has them (after **Prepare…**), otherwise donor–acceptor heavy-atom distances. Hidden Manager chains are omitted. Waters are not scored.
- **View → Pocket** — zoom to the ligand, draw nearby protein residues (within 4.5 Å) as ball-and-stick with residue labels, and show only polar hydrogens on the ligand and those residues. Select a ligand in the Manager first when more than one is loaded.
- **View → All Atoms** — draw protein residues as ball-and-stick (all atoms) instead of a ribbon cartoon (same as **Render → Protein → Ball and stick**).
- **View → Reset Camera** / right-click **Reset Structure** — restore the fitted view.
- Waters are listed but hidden by default so the fold and ligands stay readable.

## Workflow

1. Choose **Protein → Viewer**.
2. **Open** one or more PDB or mmCIF files (each becomes a named group in the Manager).
3. Rotate (left-drag), zoom (wheel), and pan (middle-drag or Ctrl+left-drag) in the canvas.
4. Select a chain or ligand in the Manager, then use **Select** to hide, focus, restyle, recolor carbons, or delete it.
5. Open **Sequence** to inspect every chain (protein, ligands, metals, waters) and highlight residues in 3D.
6. Use **View → Render** to restyle or recolor protein and ligand separately (heteroatoms stay CPK), **View → Hydrogens** to show all or only polar explicit hydrogens, **View → Hydrogen Bonds** to mark protein, ligand, and protein–ligand contacts, **View → Pocket** to inspect the binding site, or **View → All Atoms** to show protein side chains instead of ribbon.
7. Use **Prepare…** when you want a docking-ready receptor; the result is added as a second structure on top of the original.
8. Use **Select → Focus** when you want the camera on the current selection.

## Use cases

- Check a receptor–ligand complex before docking prep.
- Run **Prepare…** to rebuild gaps, strip crystallization clutter, and protonate at pH 7.4; compare the overlay with the unprepared file.
- Hide extra copies or solvent around a binding site.
- Color and restyle individual chains for a screenshot-style inspection.

## Tips and limits

Large deposits can take a moment to draw. Alternate locations and NMR ensembles beyond the first model are not split out. Delete is not undoable — reopen the file to restore removed chains. **File → Save Session** on the main window also stores every structure currently in the Protein Viewer Manager and restores them when that session is opened. Sequence edits can rename or remove existing residues; inserting new amino acids is not supported because they have no coordinates. **Prepare…** needs the docking extra (`pdbfixer`, `openmm`, `pdb2pqr`, `openmmforcefields`). Ligand Uni-pKa protonation also needs the **pka** extra. GAFF2/OpenFF Sage ligand parameterization needs **OpenFF Toolkit**, which is conda-forge only (not PyPI) and is not supported on native Windows — use Linux/macOS/WSL, or uncheck **Include ligand in PROPKA protonation** for AMBER protein-only min. **Restrained minimization** is off by default; when enabled it uses GBn2 implicit solvent with backbone restraints. Vacuum is optional and can distort charged groups. Pocket reweighting is a Coulomb estimate on pdb2pqr charges, not a bound-state pKa. PDB HETATM has no bond orders — supply ligand **SMILES** or an **SDF/MOL2** for protonation, unless the file is mmCIF with `_chem_comp_bond` for that ligand. mmCIF ligands often live on a different chain ID than the PDB auth chain (for example AXI A 2000 becoming chain B after PDBFixer); Prepare remaps those residues automatically. Select water groups in the Manager or check **Keep waters near ligand** to retain bridging waters. Metals and other HETATM are stripped unless you uncheck that option. Rebuilt internal loops from SEQRES are models, not crystallographic coordinates — **Skip loop rebuild near the ligand** is on by default. Lowercase letters in Sequence are those SEQRES gaps; Prepare models them unless you uncheck **Rebuild missing loops from SEQRES**. **Keep ligand in prepared mmCIF** is on by default; uncheck it for an apo output. Original mmCIF `_chem_comp_bond` tables are copied when present (Prepare does not rebuild ligand bond orders from RDKit). For a lighter PDBFixer-only cleanup from the main window, use **Tools → Dock → Prepare → Receptor PDB…**.
