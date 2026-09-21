# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer inventory parsing and Manager actions (no Qt WebEngine required)."""

from __future__ import annotations

from qt_helpers import qt_submenu

from pathlib import Path

from mctoolkit.protein.structure_components import (
    add_cif_chem_bond,
    add_pdb_conect,
    cif_has_component_bonds,
    cif_viewer_bond_tables,
    component_id_for_atom,
    delete_cif_atoms,
    delete_pdb_atoms,
    delete_pdb_residues,
    diff_sequence_edit,
    letter_to_resn,
    load_structure_file,
    parse_cif_chem_comp_bonds,
    parse_polymer_sequences,
    parse_structure_components,
    pdb_conect_partners,
    pdb_serial_for_atom,
    pocket_view_plan,
    polymer_sequence_entries,
    remove_cif_chem_bond,
    remove_pdb_conect,
    rewrite_pdb_residue_names,
    scope_structure_component,
    sniff_structure_format,
)
from mctoolkit.ui.protein_viewer import build_protein_viewer_html

_MINI_PDB = """\
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00           N
ATOM      2  CA  MET A   1      26.010  13.311  -8.124  1.00  0.00           C
ATOM      3  N   LEU B   2      10.000  11.000  12.000  1.00  0.00           N
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
HETATM  200  MG   MG A2001     -10.000   0.000   0.000  1.00 20.00          MG
HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O
HETATM  202  O   HOH B2003     -12.000   1.000   0.000  1.00 30.00           O
END
"""

_MINI_CIF = """\
data_test
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_model_num
ATOM 1 N N GLY A 1 1 GLY A 1.000 2.000 3.000 1
ATOM 2 C CA GLY A 1 1 GLY A 2.000 2.000 3.000 1
HETATM 3 S S24 AXI A . 2000 AXI A -26.050 -1.540 -9.129 1
HETATM 4 MG MG MG A . 2001 MG A -10.000 0.000 0.000 1
HETATM 5 O O HOH A . 2002 HOH A -11.000 1.000 0.000 1
"""

_MINI_CIF_BONDS = """\
data_lig
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_model_num
HETATM 1 C C80 LIG 1 LIG A 0.000 0.000 0.000 1
HETATM 2 O O81 LIG 1 LIG A 1.210 0.000 0.000 1
loop_
_chem_comp_atom.comp_id
_chem_comp_atom.atom_id
_chem_comp_atom.type_symbol
LIG C80 C
LIG O81 O
loop_
_chem_comp_bond.comp_id
_chem_comp_bond.atom_id_1
_chem_comp_bond.atom_id_2
_chem_comp_bond.value_order
_chem_comp_bond.pdbx_aromatic_flag
LIG C80 O81 doub N
"""

_POCKET_PDB = """\
ATOM      1  N   SER A  10       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  SER A  10       1.450   0.000   0.000  1.00  0.00           C
ATOM      3  CB  SER A  10       2.000   1.400   0.000  1.00  0.00           C
ATOM      4  OG  SER A  10       3.350   1.400   0.000  1.00  0.00           O
ATOM      5  N   ALA A  50      40.000  40.000  40.000  1.00  0.00           N
ATOM      6  CA  ALA A  50      41.500  40.000  40.000  1.00  0.00           C
HETATM  100  C1  LIG A  99       4.200   1.400   0.200  1.00  0.00           C
HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O
END
"""

_POCKET_H_PDB = """\
ATOM      1  N   SER A  10       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  SER A  10       1.450   0.000   0.000  1.00  0.00           C
ATOM      3  CB  SER A  10       2.000   1.400   0.000  1.00  0.00           C
ATOM      4  OG  SER A  10       3.350   1.400   0.000  1.00  0.00           O
ATOM      5  HG  SER A  10       3.900   2.100   0.000  1.00  0.00           H
ATOM      6  HA  SER A  10       1.700  -0.500   0.900  1.00  0.00           H
ATOM      7  N   ALA A  50      40.000  40.000  40.000  1.00  0.00           N
ATOM      8  CA  ALA A  50      41.500  40.000  40.000  1.00  0.00           C
HETATM  100  C1  LIG A  99       4.200   1.400   0.200  1.00  0.00           C
HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O
HETATM  102  HO1 LIG A  99       5.900   2.100   0.200  1.00  0.00           H
HETATM  103  H1  LIG A  99       4.000   0.500   0.700  1.00  0.00           H
HETATM  104  P1  LIG A  99       6.800   1.400   0.200  1.00  0.00           P
HETATM  105  HP1 LIG A  99       7.400   2.200   0.200  1.00  0.00           H
END
"""


def test_parse_pdb_splits_chains_ligand_metal_water():
    comps = parse_structure_components(_MINI_PDB, "pdb")
    kinds = {c.kind for c in comps}
    assert kinds == {"polymer", "ligand", "metal", "water"}
    polymers = [c for c in comps if c.kind == "polymer"]
    assert [c.chain for c in polymers] == ["A", "B"]
    assert polymers[0].n_residues == 1
    assert polymers[0].default_style == "cartoon"
    sel = polymers[0].selection
    assert sel.get("chain") == "A" or any(
        isinstance(part, dict) and part.get("chain") == "A" for part in (sel.get("and") or [])
    )
    ligand = next(c for c in comps if c.kind == "ligand")
    assert ligand.resn == "AXI"
    assert ligand.resi == "2000"
    assert ligand.chain == "A"
    assert ligand.default_style == "ballstick"
    assert ligand.selection.get("hetflag") is True
    metal = next(c for c in comps if c.kind == "metal")
    assert metal.resn == "MG"
    waters = [c for c in comps if c.kind == "water"]
    assert [c.chain for c in waters] == ["A", "B"]
    assert [c.component_id for c in waters] == ["water:A", "water:B"]
    assert all(c.n_residues == 1 for c in waters)
    assert all(c.default_visible is False for c in waters)
    assert waters[0].selection.get("chain") == "A" or any(
        isinstance(part, dict) and part.get("chain") == "A"
        for part in (waters[0].selection.get("and") or [])
    )


def test_parse_mmcif_inventory():
    comps = parse_structure_components(_MINI_CIF, "cif")
    kinds = {c.kind for c in comps}
    assert "polymer" in kinds
    assert "ligand" in kinds
    assert "metal" in kinds
    assert "water" in kinds
    polymer = next(c for c in comps if c.kind == "polymer")
    assert polymer.chain == "A"
    scoped = scope_structure_component(polymer, structure_id="s0", model=1)
    assert scoped.component_id.startswith("s0:")
    assert scoped.selection.get("model") == 1
    ligand = next(c for c in comps if c.kind == "ligand")
    assert ligand.resn == "AXI"
    assert ligand.resi == "2000"
    assert ligand.selection.get("hetflag") is True
    water = next(c for c in comps if c.kind == "water")
    assert water.chain == "A"
    assert water.component_id == "water:A"


def test_mmcif_het_keeps_numeric_label_seq_id():
    from mctoolkit.protein.structure_components import (
        atoms_to_mmcif,
        parse_structure_atoms,
        pdb_to_mmcif,
    )

    cif = pdb_to_mmcif(_MINI_PDB, data_name="mini")
    assert "AXI A . 2000" not in cif
    assert "AXI A 2000 2000" in cif
    rebuilt = atoms_to_mmcif(parse_structure_atoms(cif, "cif"), data_name="mini")
    assert "AXI A . 2000" not in rebuilt
    assert "AXI A 2000 2000" in rebuilt


def test_parse_cif_chem_comp_double_bonds():
    bonds = parse_cif_chem_comp_bonds(_MINI_CIF_BONDS)
    assert "LIG" in bonds
    assert any(b.order == 2 and {b.atom_id_1, b.atom_id_2} == {"C80", "O81"} for b in bonds["LIG"])
    tables = cif_viewer_bond_tables(_MINI_CIF_BONDS)
    assert tables["LIG"][0][2] == 2
    assert cif_has_component_bonds(_MINI_CIF_BONDS, ["LIG"])
    assert not cif_has_component_bonds(_MINI_CIF, ["AXI"])


def test_parse_cif_loops_reuses_same_text():
    from mctoolkit.protein.structure_cif import _parse_cif_loops

    first = _parse_cif_loops(_MINI_CIF_BONDS)
    second = _parse_cif_loops(_MINI_CIF_BONDS)
    assert first is second


def test_mol_from_cif_component_sets_double_bond():
    from rdkit import Chem

    from mctoolkit.workers.protein_prepare_ligand import mol_from_cif_component

    mol = mol_from_cif_component(_MINI_CIF_BONDS, "LIG")
    assert mol is not None
    assert mol.GetNumAtoms() == 2
    assert any(bond.GetBondType() == Chem.BondType.DOUBLE for bond in mol.GetBonds())


def test_sniff_cif_and_pdbqt():
    assert sniff_structure_format("foo.cif", "data_4AGC\n") == "cif"
    assert sniff_structure_format("rec.pdbqt", "ROOT\nATOM      1  C   LIG A   1\n") == "pdbqt"
    assert sniff_structure_format("x.pdb", "HEADER    TEST\n") == "pdb"


def test_load_structure_file_roundtrip(tmp_path):
    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    loaded = load_structure_file(path)
    assert loaded.sniffed_format == "pdb"
    assert loaded.viewer_format == "pdb"
    assert len(loaded.components) >= 4
    assert loaded.path.name == "mini.pdb"


def test_load_rejects_binary(tmp_path):
    path = tmp_path / "blob.pdb"
    path.write_bytes(b"HEADER\x00\x00\xff")
    try:
        load_structure_file(path)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "binary" in str(exc).lower()


def test_component_id_for_atom_prefers_ligand():
    comps = parse_structure_components(_MINI_PDB, "pdb")
    assert component_id_for_atom(comps, chain="A", resn="AXI", resi="2000") == next(
        c.component_id for c in comps if c.kind == "ligand"
    )
    assert component_id_for_atom(comps, chain="A", resn="MET", resi="1").startswith("polymer:A")
    assert component_id_for_atom(comps, chain="A", resn="HOH", resi="2002") == "water:A"
    assert component_id_for_atom(comps, chain="B", resn="HOH", resi="2003") == "water:B"
    assert component_id_for_atom(comps, chain="A", resn="MG", resi="2001").startswith("metal:")


def test_empty_non_pdb_gets_single_structure_row():
    comps = parse_structure_components("not a coordinate file", "pdb")
    assert len(comps) == 1
    assert comps[0].component_id == "structure"
    assert comps[0].selection == {}


def test_protein_viewer_help_topic():
    from mctoolkit.ui.user_guides import guide_html

    h = guide_html("protein_viewer")
    assert "Topic unavailable" not in h
    assert "Protein Viewer" in h
    assert "Goal" in h
    assert "Mol*" in h
    assert "Prepare" in h
    assert "Save to Session" in h
    assert "pose browser" in h.lower()
    assert "Open Trajectory" in h
    assert "Open Map" in h


def test_parse_polymer_sequences_one_letter_codes():
    chains = parse_polymer_sequences(_MINI_PDB, "pdb")
    assert [c.chain for c in chains] == ["A", "B"]
    assert chains[0].sequence == "M+*~"
    assert chains[1].sequence == "L~"
    kinds_a = [res.kind for res in chains[0].residues]
    assert kinds_a == ["polymer", "ligand", "metal", "water"]
    cif_chains = parse_polymer_sequences(_MINI_CIF, "cif")
    assert cif_chains[0].sequence == "G+*~"


def test_parse_polymer_sequences_includes_seqres_gaps():
    pdb = """\
SEQRES   1 A    3  MET ALA LEU
REMARK 465     ALA A    15
ATOM      1  CA  MET A  10      0.000   0.000   0.000  1.00  0.00           C
ATOM      2  CA  LEU A  20      4.000   0.000   0.000  1.00  0.00           C
END
"""
    chains = parse_polymer_sequences(pdb, "pdb")
    assert len(chains) == 1
    assert [res.kind for res in chains[0].residues] == ["polymer", "missing", "polymer"]
    assert chains[0].sequence == "MaL"
    assert chains[0].residues[1].resn == "ALA"
    assert chains[0].residues[1].resi == "15"

    cif = """\
data_gap
loop_
_pdbx_poly_seq_scheme.asym_id
_pdbx_poly_seq_scheme.mon_id
_pdbx_poly_seq_scheme.pdb_seq_num
_pdbx_poly_seq_scheme.auth_seq_num
_pdbx_poly_seq_scheme.pdb_mon_id
_pdbx_poly_seq_scheme.pdb_strand_id
_pdbx_poly_seq_scheme.pdb_ins_code
_pdbx_poly_seq_scheme.hetero
A MET 10 ? ? A . n
A ALA 15 ? ? A . n
A LEU 20 20 LEU A . n
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
ATOM 1 C CA LEU A 20 4.000 0.000 0.000
"""
    cif_chains = parse_polymer_sequences(cif, "cif")
    assert cif_chains[0].sequence == "maL"
    assert [res.kind for res in cif_chains[0].residues] == ["missing", "missing", "polymer"]
    entries = polymer_sequence_entries(cif, "cif")
    assert entries["A"][0] == ("MET", "10", "", False)


def test_4agc_sequence_includes_unobserved_nterminus():
    from pathlib import Path

    import pytest

    path = Path("samples/4AGC.cif")
    if not path.is_file():
        pytest.skip("samples/4AGC.cif is not present")
    chains = parse_polymer_sequences(path.read_text(encoding="utf-8"), "cif")
    polymer = next(c for c in chains if c.chain == "A")
    assert polymer.sequence.startswith("mgghhhhh")
    assert any(res.kind == "missing" and res.resi == "769" for res in polymer.residues)
    assert any(
        res.kind == "polymer" and res.resn == "TYR" and res.resi == "801"
        for res in polymer.residues
    )


def test_diff_sequence_edit_mutate_and_delete():
    edit = diff_sequence_edit("MAL", "MSL")
    assert edit.mutations == ((1, "S"),)
    assert edit.deletions == ()
    assert not edit.rejected_insert
    deleted = diff_sequence_edit("MAL", "ML")
    assert 1 in deleted.deletions
    assert not deleted.rejected_insert
    inserted = diff_sequence_edit("MAL", "MVAL")
    assert inserted.rejected_insert
    hetero = diff_sequence_edit("M+*~", "M+*")
    assert 3 in hetero.deletions
    assert not hetero.invalid_letter
    bad = diff_sequence_edit("MAL", "M1L")
    assert bad.invalid_letter
    assert letter_to_resn("S") == "SER"


def test_hetero_only_pdb_chains_stay_separate():
    pdb = """\
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00           N
HETATM  100  O81 AXI L2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  201  O   HOH W2002     -11.000   1.000   0.000  1.00 30.00           O
END
"""
    comps = parse_structure_components(pdb, "pdb")
    by_kind = {c.kind: c for c in comps}
    assert by_kind["polymer"].chain == "A"
    assert by_kind["ligand"].chain == "L"
    assert by_kind["ligand"].component_id.startswith("ligand:L:")
    assert by_kind["water"].chain == "W"
    assert by_kind["water"].component_id == "water:W"
    chains = parse_polymer_sequences(pdb, "pdb")
    assert [c.chain for c in chains] == ["A", "L", "W"]
    assert [c.sequence for c in chains] == ["M", "+", "~"]


def test_rewrite_and_delete_pdb_residues():
    renamed = rewrite_pdb_residue_names(_MINI_PDB, [("A", "1", "", "SER")])
    assert "SER A   1" in renamed or "SER A   1" in renamed.replace("  ", " ")
    assert "MET A   1" not in renamed
    removed = delete_pdb_residues(_MINI_PDB, {("A", "1", "")})
    assert "MET" not in removed
    assert "LEU" in removed


_CONECT_PDB = """\
HETATM  100  C80 LIG A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM  101  O81 LIG A   1       1.210   0.000   0.000  1.00  0.00           O
HETATM  102  C82 LIG A   1       2.420   0.000   0.000  1.00  0.00           C
CONECT  100  101
CONECT  101  100  102
END
"""


def test_delete_pdb_atoms_strips_conect():
    dropped = delete_pdb_atoms(_CONECT_PDB, {("A", "1", "", "C80")})
    assert "C80" not in dropped
    assert "O81" in dropped
    assert "C82" in dropped
    partners = pdb_conect_partners(dropped)
    assert 100 not in partners
    assert partners.get(101) == (102,)
    assert pdb_serial_for_atom(_CONECT_PDB, ("A", "1", "", "O81")) == 101


def test_pdb_conect_add_and_remove():
    added = add_pdb_conect(_CONECT_PDB, 100, 102)
    partners = pdb_conect_partners(added)
    assert 102 in partners[100]
    assert 100 in partners[102]
    removed = remove_pdb_conect(added, 100, 101)
    partners = pdb_conect_partners(removed)
    assert 101 not in partners.get(100, ())
    assert 102 in partners[100]


def test_delete_cif_atoms_and_chem_bonds():
    dropped = delete_cif_atoms(_MINI_CIF_BONDS, {("A", "1", "", "C80")})
    assert "C80" not in dropped
    assert "O81" in dropped
    bonds = parse_cif_chem_comp_bonds(dropped)
    assert "LIG" not in bonds
    added = add_cif_chem_bond(_MINI_CIF_BONDS.replace("doub", "sing"), "LIG", "C80", "O81", order=2)
    tables = cif_viewer_bond_tables(added)
    assert any(row[:2] == ["C80", "O81"] and row[2] == 2 for row in tables["LIG"])
    cleared = remove_cif_chem_bond(added, "LIG", "O81", "C80")
    assert "LIG" not in parse_cif_chem_comp_bonds(cleared)


def test_protein_viewer_init_script_lives_in_js_file():
    from mctoolkit.ui import protein_viewer_html

    py_path = Path(protein_viewer_html.__file__)
    js_path = py_path.with_name("protein_molstar.js")
    py = py_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")
    assert "mctoolkitLoadStructures" in js
    assert "molstar.Viewer.create" in js
    assert "mctoolkitLoadStructures" not in py
    html = build_protein_viewer_html()
    assert "mctoolkitLoadStructures" in html
    assert "molstar.js" in html or "molstar@" in html


def test_build_protein_viewer_html_has_setters():
    html = build_protein_viewer_html()
    assert "mctoolkitLoadStructures" in html
    assert "mctoolkitClearStructures" in html
    assert "mctoolkitSetDockingBox" in html
    assert "mctoolkitSetPharmacophore" in html
    assert "mctoolkitSetDockPose" in html
    assert "mctoolkitLoadTrajectory" in html
    assert "mctoolkitLoadVolume" in html
    assert "mctoolkitExportMolj" in html
    assert "mctoolkitLoadMolj" in html
    assert "qwebchannel.js" in html
    assert 'id="app"' in html


def test_build_protein_viewer_html_legacy_3dmol_setters_removed():
    html = build_protein_viewer_html()
    assert "mctoolkitSetProteinPayload" not in html
    assert "mctoolkitSetHydrogens" not in html
    assert "mctoolkitSetHbonds" not in html
    assert "mctoolkitSetPocket" not in html
    assert "applyPharmacophore" not in html


def test_protein_viewer_has_prepare_log(qapp):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    assert dlg.log.isReadOnly()
    dlg.append_log("")
    assert dlg.log.toPlainText() == ""
    dlg.append_log("hello")
    text = dlg.log.toPlainText()
    assert "hello" in text
    assert "[" in text
    dlg.close()


def test_protein_viewer_manager_hidden_until_side_dock(qapp):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    dlg.resize(1100, 720)
    dlg.show()
    qapp.processEvents()
    assert not dlg.manager.isVisible()
    status_bottom = dlg._atom_status.mapTo(dlg, dlg._atom_status.rect().bottomRight()).y()
    assert status_bottom < dlg.log.mapTo(dlg, dlg.log.rect().topLeft()).y()
    dlg.close()


def test_protein_viewer_canvas_load_overlay_nests(qapp):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    assert dlg.canvas_loading_visible() is False
    dlg.begin_canvas_load("Loading structures…", paint=False)
    assert dlg.canvas_loading_visible() is True
    assert "Loading structures" in dlg._loading_detail.text()
    dlg.begin_canvas_load("Loading structure…", paint=False)
    assert dlg.canvas_loading_visible() is True
    dlg.end_canvas_load()
    assert dlg.canvas_loading_visible() is True
    dlg.end_canvas_load()
    assert dlg.canvas_loading_visible() is False
    dlg.close()


def test_protein_embed_set_payload_quiets_resize(qapp):  # noqa: ARG001
    from mctoolkit.ui.protein_embed import ProteinEmbedView

    view = ProteinEmbedView()
    view.set_payload({"models": []})
    assert view._quiet_resize_ms == 180
    view.schedule_resize_keep_view()
    assert view._resize_timer.interval() == 180
    view.resize_keep_view()
    assert view._quiet_resize_ms == 0
    assert view._resize_timer.interval() == 50
    view.deleteLater()


def test_protein_canvas_format_maps():
    from mctoolkit.ui.protein_canvas import (
        molstar_coordinate_format,
        molstar_structure_format,
        molstar_volume_format,
    )

    assert molstar_structure_format("cif") == "mmcif"
    assert molstar_structure_format("pqr") == "pdb"
    assert molstar_coordinate_format(".dcd") == "dcd"
    assert molstar_coordinate_format("nc") == "nctraj"
    assert molstar_volume_format("mrc") == "mrc"
    assert molstar_volume_format("cub") == "cube"


def test_open_protein_viewer_shows_before_session_restore(qapp, tmp_path, monkeypatch):
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
    from mctoolkit.ui.protein_embed import ProteinEmbedView
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    seed = w.open_protein_viewer()
    seed.add_structure_path(src, refit=True)
    assert seed.save_viewer_to_session() is True
    payload = w._collect_protein_viewer()
    seed._suppress_close_prompt = True
    seed.close()
    w._protein_viewer_dialog = None
    w._protein_viewer_session = payload

    seen: list[tuple[bool, bool]] = []
    orig = ProteinViewerDialog.apply_session_state

    def wrapped(self, state):
        seen.append((self.isVisible(), self.canvas_loading_visible()))
        return orig(self, state)

    monkeypatch.setattr(ProteinViewerDialog, "apply_session_state", wrapped)
    dlg = w.open_protein_viewer()
    assert seen == [(True, True)]
    assert dlg.canvas_loading_visible() is False
    assert [slot.name for slot in dlg._slots] == ["mini.pdb"]
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()


def test_open_protein_viewer_empty_releases_start_overlay(qapp, monkeypatch):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
    from mctoolkit.ui.protein_embed import ProteinEmbedView

    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    assert dlg is not None
    assert dlg.isVisible() is True
    assert dlg._canvas_bootstrapped is True
    assert dlg.canvas_loading_visible() is False
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()


def test_reopen_protein_viewer_after_close_rebuilds_canvas(qapp, tmp_path, monkeypatch):
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
    from mctoolkit.ui.protein_embed import ProteinEmbedView

    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)
    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg.add_structure_path(src, refit=True)
    dlg._suppress_close_prompt = True
    dlg.close()
    qapp.processEvents()
    assert not dlg.isVisible()
    assert dlg.viewer._bootstrapped is False
    assert dlg._canvas_bootstrapped is False
    again = w.open_protein_viewer()
    qapp.processEvents()
    assert again is dlg
    assert again.isVisible()
    assert again._canvas_bootstrapped is True
    assert [slot.name for slot in again._slots] == ["mini.pdb"]
    again._suppress_close_prompt = True
    again.close()
    w.close()


def test_protein_embed_shutdown_web_allows_another_bootstrap(qapp):  # noqa: ARG001
    from mctoolkit.ui.protein_embed import ProteinEmbedView

    view = ProteinEmbedView()
    view._bootstrapped = True
    view._web_ready = True
    view.shutdown_web()
    assert view._bootstrapped is False
    assert view._web_ready is False
    assert view._web_shutdown is True
    view.prepare_to_show()
    view.show()
    assert view._web_shutdown is False
    view.deleteLater()


def test_atom_pick_selects_individual_atom(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,"model":0}'
    )
    hl = dlg._residue_highlight
    assert len(hl) == 1
    assert hl[0]["atom"] == "CA"
    assert hl[0]["serial"] == 2
    assert hl[0]["chain"] == "A"
    assert hl[0]["resi"] == 1
    assert "CA" in dlg._atom_status.text()
    polymer = next(r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A")
    assert polymer.selected
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","atom":"H","elem":"H","serial":9,"model":0}'
    )
    assert dlg._residue_highlight[0]["atom"] == "H"
    assert dlg._residue_highlight[0]["serial"] == 9
    assert "H" in dlg._atom_status.text()
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,'
        '"doubleClick":true,"model":0}'
    )
    res_hl = dlg._residue_highlight[0]
    assert res_hl.get("atom") in (None, "")
    assert "serial" not in res_hl
    assert res_hl["chain"] == "A"
    assert res_hl["resi"] == 1
    assert "CA" not in dlg._atom_status.text()
    assert "MET" in dlg._atom_status.text()
    polymer = next(r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A")
    assert polymer.selected
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,'
        '"doubleClick":true,"model":0}'
    )
    lig_hl = dlg._residue_highlight[0]
    assert lig_hl.get("atom") in (None, "")
    assert "serial" not in lig_hl
    ligand = next(r for r in dlg._rows if r.spec.kind == "ligand")
    assert ligand.selected
    assert not next(
        r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A"
    ).selected
    dlg.clear_selection()
    assert dlg._residue_highlight == []
    assert dlg._atom_status.text() == ""
    assert not any(r.selected for r in dlg._rows)
    dlg.close()


def test_edit_structure_two_atom_pick_and_atom_delete(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar, QMessageBox

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    mb = dlg.findChild(QMenuBar)
    edit_menu = qt_submenu(mb, "Edit")
    edit_labels = [a.text().replace("&", "") for a in edit_menu.actions() if a.text().strip()]
    assert edit_labels == [
        "Undo",
        "Redo",
        "Edit Structure",
        "Delete Atom(s)",
        "Add Bond",
        "Delete Bond",
    ]
    dlg._act_edit_structure.setChecked(True)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"O81","elem":"O","serial":100,"model":0}'
    )
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,"model":0}'
    )
    atoms = dlg._highlighted_edit_atoms()
    assert [sel["atom"] for sel in atoms] == ["O81", "C80"]
    assert dlg._act_add_bond.isEnabled() is True
    dlg.add_highlighted_bond()
    partners = pdb_conect_partners(dlg._slots[0].text)
    assert 101 in partners[100]
    assert dlg._act_undo.isEnabled() is True
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._act_edit_structure.setChecked(False)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,"model":0}'
    )
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg.delete_selected()
    text = dlg._slots[0].text
    assert " CA  MET" not in text
    assert " N   MET" in text
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    dlg.undo_manager_delete()
    assert "CA" in dlg._slots[0].text
    dlg.close()


def test_delete_selected_residue_ligand_and_undo(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,'
        '"doubleClick":true,"model":0}'
    )
    assert dlg._residue_highlight[0].get("atom") in (None, "")
    polymer_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "polymer")
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg.delete_selected()
    text = dlg._slots[0].text
    assert " MET A" not in text
    assert " LEU B" in text
    assert " AXI A" in text
    assert polymer_id in {r.spec.component_id for r in dlg._rows}
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is True
    dlg.undo_manager_delete()
    assert " MET A" in dlg._slots[0].text
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,'
        '"doubleClick":true,"model":0}'
    )
    dlg.delete_selected()
    assert " AXI A" not in dlg._slots[0].text
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    assert polymer_id in {r.spec.component_id for r in dlg._rows}
    dlg.undo_manager_delete()
    assert " AXI A" in dlg._slots[0].text
    assert any(r.spec.kind == "ligand" for r in dlg._rows)
    dlg.close()


def test_sequence_delete_is_undoable(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg._refresh_sequence_chains(force=True)
    met = next(
        res
        for chain in dlg._sequence_chains
        for res in chain.residues
        if res.chain == "A" and res.resi == "1"
    )
    dlg._on_sequence_deleted([met])
    assert " MET A" not in dlg._slots[0].text
    assert " LEU B" in dlg._slots[0].text
    assert dlg._act_undo.isEnabled() is True
    dlg.undo_manager_delete()
    assert " MET A" in dlg._slots[0].text
    dlg.close()


def test_pocket_view_plan_near_ligand_residues_and_polar_h():
    plan = pocket_view_plan(_POCKET_PDB, "pdb")
    assert plan is not None
    lig = plan.ligand_sels
    assert len(lig) == 1
    assert lig[0]["resn"] == "LIG"
    assert lig[0]["resi"] == 99
    assert lig[0].get("hetflag") is True
    nearby = {(s["resn"], s["resi"]) for s in plan.residue_sels}
    assert ("SER", 10) in nearby
    assert ("ALA", 50) not in nearby
    assert any(
        line[76:78].strip() == "H"
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM"))
    )
    ser_h = [
        (line[12:16].strip(), float(line[30:38]), float(line[38:46]), float(line[46:54]))
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM"))
        and line[76:78].strip() == "H"
        and line[17:20].strip() == "SER"
    ]
    assert ser_h
    assert all(name == "H" for name, _x, _y, _z in ser_h)
    og = (3.350, 1.400, 0.000)
    assert any(
        (x - og[0]) ** 2 + (y - og[1]) ** 2 + (z - og[2]) ** 2 <= 1.2**2 for _name, x, y, z in ser_h
    )


def test_pocket_view_plan_adds_residue_polar_h_when_only_ligand_has_hydrogens():
    pdb = _POCKET_PDB.replace(
        "HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O\nEND",
        "HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O\n"
        "HETATM  102  HO1 LIG A  99       5.900   2.100   0.200  1.00  0.00           H\nEND",
    )
    plan = pocket_view_plan(pdb, "pdb")
    assert plan is not None
    h_rows = [
        (line[17:20].strip(), line[12:16].strip())
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM")) and line[76:78].strip() == "H"
    ]
    assert ("LIG", "HO1") in h_rows
    assert any(resn == "SER" for resn, _name in h_rows)


def test_pocket_view_plan_keeps_only_polar_hydrogens():
    plan = pocket_view_plan(_POCKET_H_PDB, "pdb")
    assert plan is not None
    h_names = {
        line[12:16].strip()
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM")) and line[76:78].strip() == "H"
    }
    assert "HG" in h_names
    assert "HO1" in h_names
    assert "HP1" in h_names
    assert "HA" not in h_names
    assert "H1" not in h_names


def test_protein_menu_opens_viewer(qapp):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    labels = [a.text().replace("&", "") for a in w.menuBar().actions()]
    assert "Protein" in labels
    protein_menu = qt_submenu(w.menuBar(), "Protein")
    viewer_labels = [a.text().replace("&", "") for a in protein_menu.actions()]
    assert "Viewer" in viewer_labels
    assert any(lab.startswith("Sequence") for lab in viewer_labels)
    assert "Dock Ligand" in viewer_labels
    w.open_protein_viewer()
    dlg = w._protein_viewer_dialog
    assert dlg is not None
    assert dlg.windowTitle() == "Protein Viewer"
    assert dlg.manager.tree.topLevelItemCount() == 0
    dlg.close()
    w.close()


def test_viewer_simulate_menu_has_dock_ligand(qapp, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar

    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    tools_menu = qt_submenu(mb, "Tools")
    sim_menu = qt_submenu(tools_menu, "Simulate")
    sim_labels = [a.text().replace("&", "") for a in sim_menu.actions() if a.text().strip()]
    assert sim_labels[0] == "Dock Ligand"
    assert any(label.startswith("MM-GBSA") for label in sim_labels)
    assert any("Dynamics" in label for label in sim_labels)
    dock_menu = qt_submenu(sim_menu, "Dock Ligand")
    dock_labels = [a.text().replace("&", "") for a in dock_menu.actions() if a.text().strip()]
    assert dock_labels == ["Prepare", "Gnina…", "Pose Browser"]
    prepare_menu = qt_submenu(dock_menu, "Prepare")
    prep_labels = [a.text().replace("&", "") for a in prepare_menu.actions() if a.text().strip()]
    assert prep_labels == ["PDBQT…", "Receptor PDB…"]
    assert dlg._act_dock_viewer is not None
    assert not dlg._act_dock_viewer.isEnabled()
    dlg.close()

    w = ChemistryWorkspaceWindow()
    hosted = ProteinViewerDialog(w)
    called: list[str] = []
    monkeypatch.setattr(w, "open_gnina_dock", lambda: called.append("gnina"))
    monkeypatch.setattr(w, "open_dock_prepare", lambda: called.append("pdbqt"))
    monkeypatch.setattr(w, "open_dock_prepare_pdb", lambda: called.append("pdb"))
    monkeypatch.setattr(w, "open_dock_results_viewer", lambda: called.append("poses"))
    hosted.open_gnina_dock()
    hosted.open_dock_prepare()
    hosted.open_dock_prepare_pdb()
    hosted.open_dock_results_viewer()
    assert called == ["gnina", "pdbqt", "pdb", "poses"]
    hosted.close()
    w.close()


def test_viewer_file_and_view_menus_host_molstar(qapp):  # noqa: ARG001
    from PySide6.QtWidgets import QMenuBar

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert labels[:4] == ["File", "Edit", "Tools", "View"]
    assert "Render" not in labels
    assert "Select" not in labels
    file_menu = qt_submenu(mb, "File")
    file_labels = [a.text().replace("&", "") for a in file_menu.actions() if a.text().strip()]
    assert "Open Trajectory…" in file_labels
    assert "Open Map…" in file_labels
    assert "Export Image…" in file_labels
    view_menu = qt_submenu(mb, "View")
    view_labels = [a.text().replace("&", "") for a in view_menu.actions() if a.text().strip()]
    assert view_labels == ["Docking Box", "Reset Camera"]
    dlg.close()


def test_manager_delete_undo_redo(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_manager_selection([ligand_id])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg.delete_selected()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is True
    dlg.undo_manager_delete()
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    dlg.redo_manager_delete()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    dlg.close()


def test_manager_named_groups(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    ligand_ids = [r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand"]
    dlg._on_manager_selection(ligand_ids)
    dlg._on_add_to_group("Hits")
    assert any(g.name == "Hits" for g in dlg._named_groups)
    dlg.close()


def test_reset_camera_calls_molstar(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    calls: list[str] = []
    dlg.viewer.reset_camera = lambda: calls.append("reset")
    dlg._reset_camera()
    assert calls == ["reset"]
    dlg.close()


def test_load_trajectory_and_map_queue(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dcd = tmp_path / "run.dcd"
    dcd.write_bytes(b"DCD")
    ccp4 = tmp_path / "map.ccp4"
    ccp4.write_bytes(b"MAP")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    traj: list[dict] = []
    vols: list[dict] = []
    dlg.viewer.load_trajectory = lambda spec: traj.append(spec)
    dlg.viewer.load_volume = lambda spec: vols.append(spec)
    assert dlg.load_trajectory_path(dcd) is True
    assert traj and traj[0]["coordinates"]["fmt"] == "dcd"
    dlg.viewer.load_volume({"data": "YQ==", "fmt": "ccp4", "name": "map.ccp4"})
    assert vols and vols[0]["fmt"] == "ccp4"
    dlg.close()


def test_md_finished_loads_dcd(qapp, tmp_path):  # noqa: ARG001
    from types import SimpleNamespace

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    out = tmp_path / "md.pdb"
    out.write_text(_MINI_PDB, encoding="utf-8")
    dcd = tmp_path / "md.dcd"
    dcd.write_bytes(b"DCD")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(src)
    loaded: list[str] = []
    dlg.load_trajectory_path = lambda path, slot=None: loaded.append(str(path)) or True
    dlg._on_md_finished(SimpleNamespace(structure_path=str(out), dcd_path=str(dcd)))
    assert any(slot.name == "md.pdb" for slot in dlg._slots)
    assert loaded and loaded[0].endswith("md.dcd")
    dlg.close()


def test_unscoped_component_id():
    from mctoolkit.ui.protein_viewer_models import unscoped_component_id

    assert unscoped_component_id("s0:ligand:A:AXI:2000") == "ligand:A:AXI:2000"
    assert unscoped_component_id("s12:polymer:A") == "polymer:A"
    assert unscoped_component_id("ligand:A:AXI:2000") == "ligand:A:AXI:2000"


def test_multi_file_session_and_prepare_overlay(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    a = tmp_path / "first.pdb"
    b = tmp_path / "second.pdb"
    a.write_text(_MINI_PDB, encoding="utf-8")
    b.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.add_structure_path(a, refit=True)
    dlg.add_structure_path(b, refit=False)
    names = [
        dlg.manager.tree.topLevelItem(i).text(0)
        for i in range(dlg.manager.tree.topLevelItemCount())
    ]
    assert names == ["first.pdb", "second.pdb"]
    assert len(dlg._slots) == 2
    prepared = tmp_path / "first_prepared.pdb"
    prepared.write_text(_MINI_PDB, encoding="utf-8")
    dlg._on_structure_prepared(str(prepared))
    names = [
        dlg.manager.tree.topLevelItem(i).text(0)
        for i in range(dlg.manager.tree.topLevelItemCount())
    ]
    assert "first.pdb" in names
    assert "first_prepared.pdb" in names
    assert "second.pdb" in names
    assert len(dlg._slots) == 3
    dlg.close()


def test_second_structure_appends_without_replacing_canvas(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    a = tmp_path / "first.pdb"
    b = tmp_path / "second.pdb"
    a.write_text(_MINI_PDB, encoding="utf-8")
    b.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    sets: list[dict] = []
    adds: list[dict] = []
    monkeypatch.setattr(dlg.viewer, "load_structures", lambda payload: sets.append(payload))
    monkeypatch.setattr(dlg.viewer, "add_structures", lambda payload: adds.append(payload))
    dlg.viewer._web_ready = True
    dlg.add_structure_path(a, refit=True)
    assert len(sets) == 1
    assert len(sets[0]["models"]) == 1
    assert adds == []
    dlg.add_structure_path(b, refit=False)
    assert len(sets) == 1
    assert len(adds) == 1
    assert len(adds[0]["models"]) == 1
    dlg.close()


def test_delete_extra_structures_keeps_first(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    files = []
    for name in ("one.pdb", "two.pdb", "three.pdb"):
        path = tmp_path / name
        path.write_text(_MINI_PDB, encoding="utf-8")
        files.append(path)
    dlg = ProteinViewerDialog()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    for path in files:
        dlg.add_structure_path(path, refit=False)
    assert len(dlg._slots) == 3
    keep_id = dlg._slots[0].structure_id
    dlg.manager.tree.clearSelection()
    for i in range(1, dlg.manager.tree.topLevelItemCount()):
        dlg.manager.tree.topLevelItem(i).setSelected(True)
    dlg.delete_selected_chains()
    assert [slot.structure_id for slot in dlg._slots] == [keep_id]
    dlg.close()


def test_4agc_cif_axitinib_has_carbonyl_double():
    from pathlib import Path

    import pytest
    from rdkit import Chem

    from mctoolkit.workers.protein_prepare_ligand import mol_from_cif_component

    path = Path("samples/4AGC.cif")
    if not path.is_file():
        pytest.skip("samples/4AGC.cif is not present")
    text = path.read_text(encoding="utf-8")
    bonds = parse_cif_chem_comp_bonds(text).get("AXI") or ()
    assert any({b.atom_id_1, b.atom_id_2} == {"C80", "O81"} and b.order == 2 for b in bonds)
    tables = cif_viewer_bond_tables(text)
    assert any(row[2] == 2 for row in tables.get("AXI", []))
    mol = mol_from_cif_component(text, "AXI")
    assert mol is not None
    assert any(bond.GetBondType() == Chem.BondType.DOUBLE for bond in mol.GetBonds())


def test_save_structure_writes_active_slot(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PySide6.QtWidgets import QFileDialog, QMenuBar

    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    dest = tmp_path / "out.pdb"
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(src)
    mb = dlg.findChild(QMenuBar)
    file_menu = qt_submenu(mb, "File")
    labels = [a.text().replace("&", "") for a in file_menu.actions()]
    assert "Save Structure…" in labels
    assert "Save to Session" in labels
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), "PDB (*.pdb)"))
    dlg.save_structure_dialog()
    saved = dest.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert saved.replace("\r\n", "\n") == _MINI_PDB.replace("\r\n", "\n")
    dlg.close()


def test_collect_session_state_keeps_structures_and_molj_slot(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.protein_viewer import ProteinViewerDialog

    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.add_structure_path(first, refit=True)
    dlg.add_structure_path(second, refit=False)
    state = dlg.collect_session_state()
    assert state is not None
    assert [s["name"] for s in state["structures"]] == ["first.pdb", "second.pdb"]
    assert "splitters" in state
    assert "allAtoms" not in state
    dlg.viewer.fetch_molj = lambda timeout_ms=400: {"kind": "molj", "ok": True}
    state = dlg.collect_session_state()
    assert state["molj"] == {"kind": "molj", "ok": True}
    dlg2 = ProteinViewerDialog()
    loaded: list[dict] = []
    dlg2.viewer.load_molj = lambda state: loaded.append(state)
    dlg2.apply_session_state(state)
    assert [slot.name for slot in dlg2._slots] == ["first.pdb", "second.pdb"]
    assert dlg2.manager.tree.topLevelItemCount() == 2
    assert loaded == [{"kind": "molj", "ok": True}]
    dlg.close()
    dlg2.close()


def test_save_to_session_is_required_for_cms(qapp, tmp_path):  # noqa: ARG001
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg.add_structure_path(src, refit=True)
    assert w._collect_protein_viewer() is None
    assert dlg.save_viewer_to_session() is True
    payload = w._collect_protein_viewer()
    assert isinstance(payload, dict)
    assert payload["structures"][0]["name"] == "mini.pdb"
    assert w._session_has_unsaved_changes()
    dlg.close()
    w.close()


def test_close_without_save_to_session_discards_live_viewer(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(first, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted()
    assert w._collect_protein_viewer() is None

    dlg.show()
    dlg.add_structure_path(first, refit=True)
    assert dlg.save_viewer_to_session() is True
    dlg.close_structure()
    dlg.add_structure_path(second, refit=True)
    ev2 = QCloseEvent()
    dlg.closeEvent(ev2)
    assert ev2.isAccepted()
    kept = w._collect_protein_viewer()
    assert kept["structures"][0]["name"] == "first.pdb"
    w.close()


def test_close_save_to_session_commits_live_viewer(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "live.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(src, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted()
    payload = w._collect_protein_viewer()
    assert payload["structures"][0]["name"] == "live.pdb"
    w.close()


def test_close_cancel_keeps_protein_viewer_open(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(src, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert not ev.isAccepted()
    assert dlg.isVisible()
    assert w._collect_protein_viewer() is None
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()
