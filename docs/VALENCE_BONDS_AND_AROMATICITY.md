# Valence, bonds, aromaticity, and atom types in MCtoolkit

Authoritative summary of how the **2D sketcher** and **RDKit-backed** table chemistry treat valence, bond order, bond “types”, aromaticity, and what counts as an atom type. For stereoisomerism (E/Z, wedges, etc.) see [`STEREO_AND_ISOMERISM.md`](STEREO_AND_ISOMERISM.md).

## 1. Valence (in the sketcher)

**Valence** here means how much bonding an atom is carrying **in the drawn graph**, compared to a **simple allowed maximum** used for UI warnings—not a full quantum or formal oxidation-state model.

- **`_current_valence(node_id)`** (`widget.py`): sum of **bond orders** (1, 2, or 3) over every bond incident to that node. Explicit hydrogens on the canvas count like any other neighbor.
- **`_max_bond_order_sum_for_node` / `_max_bond_order_sum`**: charge-aware cap on that sum, derived mainly from RDKit’s **`GetDefaultValence`** for the element, with small adjustments for common ions (e.g. `N+`, `O-`) and fallbacks for metals/odd cases. **Wildcard** nodes use the **maximum** cap over their allowed element list.
- **`_valence_violations`**: atoms whose current sum **exceeds** the cap are flagged for display; export still defers to **RDKit sanitization** (`chem._sanitize_mol_for_smiles` and fallbacks), which may accept some drawings the local heuristic flags.

Implicit hydrogens are **not** auto-added into the graph for valence arithmetic; the cap is chosen so that typical “implicit H” organic drawing stays within bounds when bond orders match default valence expectations.

---

## 2. Bond order (internal model)

Each sketch bond is stored as `(a_id, b_id, order, stereo)` with:

| `order` | Meaning on canvas | RDKit type when building mol from sketch |
|--------:|-------------------|------------------------------------------|
| **1** | Single line (or wedge/hash if `stereo` ≠ 0) | `BondType.SINGLE` |
| **2** | Two parallel strokes | `BondType.DOUBLE` |
| **3** | Three parallel strokes | `BondType.TRIPLE` |

`stereo` is only meaningful for **`order == 1`** (tetrahedral wedge/hash); see the stereo doc.

Bond order is what **valence sums use** (double = 2 toward both endpoints).

---

## 3. Bond types (chemistry vs implementation)

Chemically, “bond type” can mean **order** (single/double/triple), **polarity** (ionic/covalent), **aromatic** (delocalized π), **coordination**, etc.

**MCtoolkit sketcher:**

- Represents **covalent orders 1–3** explicitly.
- Does **not** store a separate “aromatic bond” order in the tuple; see **Aromaticity** below.
- **Ionic / dative** bonds are not first-class drawing tools; salts may appear as **grouped fragments** with distinct mols in SMILES export, not as bond-type toggles on the canvas.

---

## 4. Aromaticity

**Aromaticity** is a model (often Hückel-type rules) applied to cyclic π systems. **RDKit** assigns aromatic flags during **sanitization** when building or reading molecules.

**Loading from table / `load_from_rdkit_mol`:**

- Immediately before copying bonds into the sketch, **`Kekulize(..., clearAromaticFlags=True)`** localizes aromatic rings to alternating single/double (`_kekulize_for_sketch_orders`). This is required because sanitize / AddHs (e.g. stereochemical H) re-aromatize bonds after any earlier Kekulize.
- If Kekulize still fails, remaining **`BondType.AROMATIC`** bonds fall back to sketch **`order == 1`**. There is **no** separate “aromatic line style” in the internal bond record.

**Exporting sketch → RDKit mol:**

- Bonds are **`SINGLE` / `DOUBLE` / `TRIPLE`** only; there is **no** explicit “aromatic bond” bit from the sketch alone. RDKit may **re-aromatize** on sanitize depending on the graph you drew.

**Implication:** benzene drawn as alternating double/single in the sketch is that **Kekulé form** in the mol until RDKit’s chemistry layer interprets the ring. Fully delocalized drawing conventions (circle-in-ring) are **not** encoded as a distinct bond type in this UI.

---

## 5. Atom types (elements, charges, wildcards)

**Normal atoms**

- **Element symbol** (e.g. `C`, `N`, `Cl`) from the periodic table, validated via RDKit when parsed from free text (`chem._parse_atom_symbol_input`).
- Toolbar / palette lists live in **`constants.py`** (`SKETCH_ELEMENT_SYMBOLS`, `TOOLBAR_ELEMENT_SYMBOLS`, maps for uppercase aliases).

**Isotopes**

- **`D`** (deuterium) is included in the symbol list like other elements; `T` is recognized in valence helpers where noted.

**Formal charge**

- Stored on nodes (optional `charge`); included when building RDKit atoms and in **valence cap** logic (`_max_bond_order_sum`).

**Wildcard (`*`)**

- Used for **substructure-style** query atoms; a configurable list of allowed elements (`wildcard_els`) backs SMARTS generation (`wildcards` module). Valence warnings use the **strictest** cap across those elements.

**Anything else**

- Exotic atoms not on the palette can often still be typed in **Edit atom** if RDKit accepts the symbol; rendering and valence rules still use the same pathways.

**2D label colors (sketcher)**

- Element symbols use the same **default atomic palette** as RDKit MolDraw2D’s ``assignDefaultPalette`` (see `element_colors.py`): e.g. N blue, O red, F cyan, Cl green, C/H black, metals not in the sparse table render black like RDKit’s fallback. Wildcard (`*`) keeps its own purple styling.

---

## Quick reference: where this lives in code

| Topic | Primary location |
|--------|------------------|
| Bond tuple layout, sanitize on load | `molmanager/ui/sketcher/widget.py` (`load_from_rdkit_mol`, `_mol_from_node_ids`) |
| Valence sums and caps | `SketchWidget._current_valence`, `_max_valence`, `_max_bond_order_sum*` in `widget.py` |
| Bond drawing (order 1/2/3) | `molmanager/ui/sketcher/widget_painting.py` (`_draw_bond_line`) |
| Element lists & maps | `molmanager/ui/sketcher/constants.py` |
| Atom text parsing | `molmanager/ui/sketcher/chem.py` |
| Element label RGB (RDKit default palette) | `molmanager/ui/sketcher/element_colors.py` |
| Sanitize / export fallbacks | `molmanager/ui/sketcher/chem.py` (`_sanitize_mol_for_smiles`) |

When changing bond or valence behavior, update **this file** and any user-facing tooltips or status strings that mention “valence” or bond types.
