# Stereochemistry and isomerism in MCtoolkit

This document is the **authoritative in-repo summary** of how MCtoolkit (including the 2D sketcher) treats common kinds of isomerism. It is meant for developers and power users; it does not replace IUPAC definitions. For **valence, bond order, aromaticity, and atom types**, see [`VALENCE_BONDS_AND_AROMATICITY.md`](VALENCE_BONDS_AND_AROMATICITY.md).

---

## 1. Isomerism (overview)

**Isomers** share the same molecular formula but differ in structure or spatial arrangement.

| Kind | Idea | Typical representation in MCtoolkit |
|------|------|----------------------------------------|
| **Constitutional (structural)** | Different connectivity | The graph of atoms and bonds you draw or load from SMILES/MOL |
| **Stereoisomerism** | Same connectivity, different 3D arrangement not interconvertible by rotation about single bonds (without breaking bonds) | Wedge/hash bonds, double-bond geometry, and (when present in source data) RDKit stereo flags on export |

The table and sketcher hold **one specific structure** at a time per row or canvas. They do **not** automatically enumerate all isomers of a scaffold unless you use a dedicated tool (e.g. R-group or external enumeration).

---

## 2. Stereoisomerism (general)

Stereoisomers include **enantiomers** (non-superimposable mirror images) and **diastereomers** (any stereoisomer pair that are not mirror images).

MCtoolkit uses **RDKit** for chemistry semantics. The sketcher:

- Encodes **tetrahedral** configuration with **wedge** and **hash (dashed wedge)** on **single bonds** only. The **narrow end of the wedge/hash is the stereogenic center** (first atom in the internal bond tuple; see `widget_painting` and `bonds.reorient_wedged_bonds_tip_away_from_multiples`).
- Rebuilds an `RWMol` from the sketch, sets `BondDir` for wedges, runs `AssignChiralTypesFromBondDirs` and CIP labeling where possible (`_mol_from_node_ids`, `_apply_sketch_coords_and_stereo`).

**Limits:** Allene, square-planar, octahedral, and other non-tetrahedral stereo are not first-class in the sketcher UI. Exotic cases may be skipped or misclassified; prefer loading a well-specified mol block from the table when stereo is critical.

---

## 3. E/Z (alkene stereochemistry)

**Cahn–Ingold–Prelog (CIP)** priorities at **each** alkene carbon determine which substituent is “higher priority” on each side. **E** (*entgegen*) = higher-priority groups on **opposite** sides of the double bond; **Z** (*zusammen*) = on the **same** side (in the usual projection).

MCtoolkit’s sketcher **infers** E/Z labels from **2D coordinates** plus ligand priorities (`molmanager/ui/sketcher/alkene_stereo.py`):

- Uses a hydrogen-supplemented copy with `CanonicalRankAtoms(breakTies=True)` to pick the highest-priority ligand at each end of each **non-aromatic** double bond, then compares which side of the C=C axis those ligands lie on (2D cross product sign).
- This matches **textbook E/Z** for typical organic drawings; it is **not** a full CIP implementation for every edge case (ties, collinear atoms, exotic heteroatom alkenes may yield **no label**).

**cis/trans** is an older geometric language for disubstituted alkenes; it does not always coincide with E/Z when substituents differ. The app reports **E/Z**, not cis/trans, for alkene bonds.

---

## 4. Diastereoisomerism (diastereomers)

**Diastereomers** are stereoisomers that are **not** mirror images of each other (e.g. (2R,3R) vs (2R,3S) of a molecule with two stereocenters).

MCtoolkit:

- Stores **one** stereoisomer per structure (per row / per sketch).
- Can compare or filter structures (e.g. substructure search) **as drawn**; it does **not** automatically generate or rank all diastereomers of a core.
- When multiple stereocenters exist, wedge/hash choices determine **relative** configuration; R/S labels from RDKit reflect that single diastereomer.

---

## 5. Tautomerism

**Tautomers** are isomers interconvertible by **formal migration** of a proton (or, more broadly, valence tautomerism). Classic examples: keto–enol, imine–enamine, some heterocycle NH shifts.

Important for this app:

- A **SMILES string or mol block** almost always represents **one tautomeric form** (the one you drew or that the supplier encoded).
- **RDKit** `MolFromSmiles` / sanitization do **not** mean “all tautomers”; they mean “this graph.” MCtoolkit does **not** ship a global “canonical tautomer” or tautomer enumeration pass on every table load.
- If you need a specific tautomer, **draw or paste that form** explicitly. For batch canonicalization, use RDKit’s `MolStandardize` (or similar) outside the app or extend workers with care—different pipelines pick different “preferred” tautomers.

---

## 6. Atropisomerism

**Atropisomers** arise when **restricted rotation** about a bond (often a biaryl axis) makes **non-interconvertible** conformers that can be isolated or treated as stereoisomers at laboratory timescales.

MCtoolkit:

- The **2D sketcher** does **not** encode **axial chirality** (e.g. BINAP-style axis) as a first-class tool; a flat drawing of a biaryl is ambiguous unless the **source mol** carries appropriate stereo (depending on RDKit version and mol format).
- **3D** workflows (e.g. conformer generation in `workers/chemistry_tools.py`) operate on the connectivity and stereo RDKit knows about; they do **not** infer atropisomerism from a generic 2D sketch alone.

For atropisomer-sensitive chemistry, prefer **explicit structures from trusted mol blocks** or 3D tools that assign/retain axis stereo, and treat plain 2D sketches as **configurationally incomplete** unless you verify the exported mol.

---

## Quick reference: where this lives in code

| Topic | Primary location |
|--------|-------------------|
| Wedge/hash semantics & bond tuple | `molmanager/ui/sketcher/bonds.py`, `widget_painting.py`, `widget.py` |
| E/Z inference | `molmanager/ui/sketcher/alkene_stereo.py` |
| R/S and chiral perception from sketch | `SketchWidget._mol_from_node_ids`, `_apply_sketch_coords_and_stereo`, `_recompute_chiral_highlights` in `widget.py` |
| Load mol → sketch (RDKit wedges) | `SketchWidget.load_from_rdkit_mol` |

When changing stereo behavior, update **this file** and any affected docstrings so the sketcher and the rest of MCtoolkit stay aligned.

Related: [`VALENCE_BONDS_AND_AROMATICITY.md`](VALENCE_BONDS_AND_AROMATICITY.md) (bond orders, aromaticity on load/export, valence heuristics).
