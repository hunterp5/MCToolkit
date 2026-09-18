# Pharmacophore

Build a 3D pharmacophore in Protein Viewer, save it as its own file, and apply it when docking with Gnina.

## Goal

Mark sites in the pocket (H-bond donors and acceptors, aromatic centroids, hydrophobes, and other RDKit BaseFeatures families) so later docking runs prefer those regions.

## When to use

Use **Protein Viewer → Pharmacophore** after a structure is on the canvas and you want reusable spatial constraints. Use **Protein → Dock Ligand → Gnina → Pharmacophore** to apply a saved file.

## Inputs / scope

Features are spheres in Cartesian coordinates (Å). Click an atom to place a site at that atom, type an XYZ, or generate sites from a ligand with RDKit. Empty canvas space is not pickable in 3Dmol.

The file format is JSON (`molmanager.pharmacophore` version 1), typically `.json` or `.mph4`. It is independent of the MolManager session file; **Save…** writes it for other sessions.

Gnina does not have a native pharmacophore flag. MolManager converts enabled features to an AutoDock map (`--user_grid` / `--user_grid_lambda`). Attractive families are negative Gaussian wells; **Exclusion** is repulsive. The map is occupancy-based (feature type is not encoded per atom type).

## Options

- **Edit Pharmacophore…** — table of features (on/off, type, X/Y/Z, radius) and placement controls.
- **Place on atom click** — the next 3D atom click inserts a feature using the current type and radius.
- **Add at coordinates** — insert at explicit X/Y/Z (Å).
- **Type** — RDKit BaseFeatures families: H-bond donor, H-bond acceptor, aromatic, hydrophobe, lumped hydrophobe, positive/negative ionizable, zinc binder, plus **Exclusion**.
- **Radius** — sphere radius in Å (also sets the Gaussian width of the Gnina well).
- **From ligand** — RDKit `BaseFeatures.fdef` sites from the selected ligand (or every ligand if none is selected).
- **Open… / Save…** — load or write the pharmacophore JSON.
- **Clear** — remove all features from this viewer.
- **Send to Gnina** — write the file if needed and fill the Gnina **Pharmacophore** field.
- **Gnina → Pharmacophore / λ** — path to the JSON and `--user_grid_lambda` (default 1).

## Workflow

1. Open **Protein → Viewer** and load a complex.
2. Choose **Pharmacophore → Edit Pharmacophore…**.
3. Place sites on atoms, add XYZ, or **From ligand**. Adjust type and radius in the table.
4. **Save…** the pharmacophore for reuse.
5. **Send to Gnina** (or browse the file in the Gnina dialog) and run docking as usual.

## Use cases

- Recapitulate a crystal ligand’s donors, acceptors, and aromatic centroid, then dock analogs into the same wells.
- Add an **Exclusion** sphere to keep poses out of an unproductive subpocket.
- Reload a saved pharmacophore in a later session without rebuilding the viewer layout.
