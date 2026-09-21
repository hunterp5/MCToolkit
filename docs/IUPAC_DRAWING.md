# IUPAC Drawing Standards in the mctoolkit Sketcher

Mapped from the [IUPAC Recommendations 2008](https://iupac.qmul.ac.uk/drawing/drawing.html) (GR-\*) and the [2006 stereochemical configuration](https://publications.iupac.org/pac/2006/pdf/7810x1897.pdf) recommendations (ST-\*). Project rule: `.cursor/rules/iupac-drawing-sketcher.mdc`.

## Rendering

| Topic | IUPAC | Sketcher |
|-------|-------|----------|
| Fonts | GR-0 Helvetica/Arial, plain roman | `iupac_structure_font`; CIP/E/Z italic |
| Bond termini | GR-2.1.5 | Label insets + stereo distal trim |
| Bond lengths | GR-1.1 | Median `SKETCH_MEDIAN_BOND_PX`; ring chords via `ring_circumradius_for_bond_length` |
| Bond widths | GR-1.2 | `iupac_sketch_style` ≈ label stroke |
| Hash spacing | GR-1.3 | `hash_bar_count_for_style` |
| Hashed / solid wedge | ST | Tip = first atom in bond tuple |
| Double bonds | GR-1.10 | Offset / centered; fusion face by double count |
| Carbon / condensed H | GR-2 | Skeletal C; `OH`, `NH2`, … |
| Label orientation | GR-2.1.6 | Reverse multi-char when bonds on right only (`iupac_labels`) |
| Bond → label | GR-2.1.5 | Inset to attachment character (first / last when reversed) |
| Contracted groups | GR-2.2 / GR-2.3 | Text mode abbreviations |
| Charges / lone pairs | GR-5 | Charges on labels; optional lone pairs |
| Stereo descriptors | ST-0.7 / GR-11.1–11.2 | `(R)`/`(S)`, `(E)`/`(Z)` clear of ink |
| Orientation | GR-3.1–3.4 | Principal (largest) ring system drives pose (GR-3.4.1); heteroatoms right; bottom-left rings; no bond stack/cross |
| Bond overlap | GR-3.3.4 | Crossing / coincident-bond penalty in layout; validator flags `bond_crossing` / `bond_overlap` |
| Stereo annotations | GR-11.1–11.2 | CIP/E/Z placed by collision search clear of bonds and atom labels |

## Rings and macrocycles (GR-3.3)

| Topic | IUPAC | Sketcher |
|-------|-------|----------|
| ≤8 atoms | Regular polygons | `regular_ring_offsets_y_up` |
| ≥9 atoms | Reentrant hexagonal (not circular); prefer 120° | `large_ring_offsets_y_up` (hex-lattice; odd = n+1 hex minus a vertex) |
| Double bonds in large rings | Configuration never sacrificed | Hex template + reflection pick; triples stay on CoordGen (linear) |
| Heteroatoms | Inward-facing when free | `rotate_offsets_to_inward_heteroatoms` |
| Triples in large rings | Linear | Skip hex refine when ring has triples |
| Ortho-fusion | Shared bond; cis-like on large rings | `fusion_ring_offsets_for_bond` / drop template on bond |
| Bridged / congested | Balance rings vs bridges | CoordGen preferred in Clean Up |
| Spiro | Second ring in free sector | `spiro_second_ring_offsets_y_up` |
| Ring substituents | Larger exterior bisector + 30° snap | `exterior_ring_substituent_direction` |
| Fit to canvas | Structures stay in viewport | `ensure_sketch_fits_viewport` after import / Clean Up / templates / resize |
| Table → sketcher | Exact table picture orientation | `load_from_rdkit_mol` uses RDKit default 2D / existing SDF coords (`_depict_mol_2d_table_match`); no IUPAC orient/hex |
| Stereo hydrogens | Only when needed (ST-1.2) | Explicit H only if no suitable wedge/hash substituent; ring centers prefer exocyclic ligands (ST-1.3); else omit H |
| Macrocycle stereo | Preserve tags through layout | Capture chiral tags → reshape → restore → `WedgeMolBonds` + CIP (Clean Up path) |

Templates include cycloheptane–cyclododecane. Isolated ≥9-membered rings are forced to hexagonal GR-3.3.2 geometry after Clean Up (and interactive tidy), not when loading from the table.

## Clean Up and validation

- Sanitize → CoordGen preference → `Compute2DCoords` → `iupac_orient` → isolated macrocycle refine → rescale → stereo sanitize → `validate_iupac_sketch`.
- Validator: stereo-between-centers, stereo on multiples, bond-length outliers, near-collinear singles, atom overlap.

## Interactive constraints

- New bonds snap to median length and ~109.5° / 120° / 180°.
- Ring→substituent: GR-4.2.1 exterior bisector.
- Shift disables snap while dragging.
- ST-0.5 blocks wedge/hash between two chiral centers.

## Deferred

Aromatic circle depiction (GR-6), salt layout (GR-7), variable attachment (GR-9), class-specific natural-product orientations, Newman/Haworth/Fischer projections.
