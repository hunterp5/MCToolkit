# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer inventory parsing and Manager actions (no Qt WebEngine required)."""

from __future__ import annotations

from molmanager.structure_components import (
    cif_has_component_bonds,
    cif_viewer_bond_tables,
    component_id_for_atom,
    delete_pdb_residues,
    diff_sequence_edit,
    letter_to_resn,
    load_structure_file,
    parse_cif_chem_comp_bonds,
    parse_polymer_sequences,
    parse_structure_components,
    pocket_view_plan,
    polymer_sequence_entries,
    rewrite_pdb_residue_names,
    scope_structure_component,
    sniff_structure_format,
)
from molmanager.ui.protein_viewer import build_protein_viewer_html

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
    from molmanager.structure_components import atoms_to_mmcif, parse_structure_atoms, pdb_to_mmcif

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


def test_mol_from_cif_component_sets_double_bond():
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import mol_from_cif_component

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
    from molmanager.ui.user_guides import guide_html

    h = guide_html("protein_viewer")
    assert "Topic unavailable" not in h
    assert "Protein Viewer" in h
    assert "Goal" in h
    assert "Manager" in h
    assert "Sequence" in h
    assert "Prepare" in h
    assert "Color" in h
    assert "Select" in h


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


def test_build_protein_viewer_html_has_setters():
    html = build_protein_viewer_html()
    assert "molmanagerSetProteinPayload" in html
    assert "payload.models" in html
    assert "molmanagerApplyComponentStates" in html
    assert "molmanagerDeleteComponents" in html
    assert "molmanagerZoomToComponents" in html
    assert "molmanagerSetResidueHighlight" in html
    assert "molmanagerSetPocket" in html
    assert "applyPocketOverlay" in html
    assert "addPocketResidueLabels" in html
    assert "addResLabels" in html
    assert "molmanagerMutateResidues" in html
    assert "molmanagerDeleteResidues" in html
    assert "Reset Structure" in html
    assert "__RESET_JS__" not in html
    assert "qwebchannel.js" in html
    assert "cartoon" in html
    assert "applyCifBondOrders" in html
    assert "md.cifBonds" in html
    assert "carbonScheme" in html
    assert "carbonSpec" in html
    assert "v.setStyle({}, {})" in html
    assert "hetflag: true" in html


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


def test_protein_menu_opens_viewer(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemicalTableApp

    w = ChemicalTableApp()
    labels = [a.text().replace("&", "") for a in w.menuBar().actions()]
    assert "Protein" in labels
    protein_menu = next(
        a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Protein"
    )
    viewer_labels = [a.text().replace("&", "") for a in protein_menu.actions()]
    assert "Viewer" in viewer_labels
    w.open_protein_viewer()
    dlg = w._protein_viewer_dialog
    assert dlg is not None
    assert dlg.windowTitle() == "Protein Viewer"
    assert dlg.manager.tree.topLevelItemCount() == 0
    dlg.close()
    w.close()


def test_manager_hide_select_delete(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.protein_viewer import _ID_ROLE, ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert not hasattr(dlg.manager, "btn_open")
    assert not hasattr(dlg.manager, "hint")
    assert not hasattr(dlg.manager, "btn_hide")
    ids = [r.spec.component_id for r in dlg._rows]
    assert any("polymer:A" in i for i in ids)
    assert dlg.manager.tree.topLevelItemCount() == 1
    assert dlg.manager.tree.topLevelItem(0).text(0) == "mini.pdb"
    chain_labels = [
        dlg.manager.tree.topLevelItem(0).child(i).text(0)
        for i in range(dlg.manager.tree.topLevelItem(0).childCount())
    ]
    assert chain_labels == ["Chain A", "Chain B"]
    chain_a = dlg.manager.tree.topLevelItem(0).child(0)
    assert [chain_a.child(i).text(0) for i in range(chain_a.childCount())] == [
        "Polymer",
        "AXI 2000",
        "MG 2001",
        "Water",
    ]
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    water_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "water")
    assert next(r for r in dlg._rows if r.spec.component_id == water_id).visible is False

    dlg._on_visibility_changed(ligand_id, False)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is False

    dlg._on_manager_selection([ligand_id])
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).selected is True
    assert next(r for r in dlg._rows if r.spec.kind == "polymer").selected is False

    dlg._on_style_requested("stick")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).style == "stick"
    assert next(r for r in dlg._rows if r.spec.kind == "polymer").style == "cartoon"

    dlg._apply_selected_color("green")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).color_scheme == "green"
    assert all(r.color_scheme == "default" for r in dlg._rows if r.spec.kind == "polymer")
    lig_payload = next(p for p in dlg._component_payloads() if p["kind"] == "ligand")
    assert lig_payload["carbonScheme"] == "greenCarbon"

    dlg._set_selected_visible(False)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is False
    dlg._set_selected_visible(True)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is True

    dlg._apply_selected_color("#fa8072")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).color_scheme == "#fa8072"
    lig_payload = next(p for p in dlg._component_payloads() if p["kind"] == "ligand")
    assert lig_payload["carbonScheme"] == "#fa8072"

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    ligand_item = None
    for i in range(dlg.manager.tree.topLevelItemCount()):
        file_item = dlg.manager.tree.topLevelItem(i)
        for j in range(file_item.childCount()):
            group = file_item.child(j)
            for k in range(group.childCount()):
                item = group.child(k)
                if item.data(0, _ID_ROLE) == ligand_id:
                    ligand_item = item
    assert ligand_item is not None
    dlg.manager.tree.clearSelection()
    ligand_item.setSelected(True)
    dlg.delete_selected()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    dlg.close()


def test_sequence_window_select_and_edit(qapp, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QMenuBar

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert [c.sequence for c in dlg._sequence_chains] == ["M+*~", "L~"]
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert "Sequence" in labels
    assert "Select" in labels
    assert any(label.startswith("Prepare") for label in labels)
    select_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Select")
    select_labels = [a.text().replace("&", "") for a in select_menu.actions() if a.text().strip()]
    assert select_labels[:4] == ["Hide", "Show", "Focus", "Delete"]
    assert "Render" in select_labels
    assert "Color" in select_labels
    select_render = next(
        a.menu() for a in select_menu.actions() if a.text().replace("&", "") == "Render"
    )
    select_color = next(
        a.menu() for a in select_menu.actions() if a.text().replace("&", "") == "Color"
    )
    assert "Cartoon" in [a.text().replace("&", "") for a in select_render.actions()]
    assert "Custom…" in [a.text().replace("&", "") for a in select_color.actions()]
    view_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "View")
    view_labels = [a.text().replace("&", "") for a in view_menu.actions() if a.text().strip()]
    assert "Render" in view_labels
    assert "Pocket" in view_labels
    assert "All Atoms" in view_labels
    render_menu = next(
        a.menu() for a in view_menu.actions() if a.text().replace("&", "") == "Render"
    )
    render_labels = [a.text().replace("&", "") for a in render_menu.actions()]
    assert "Protein" in render_labels
    assert "Ligand" in render_labels
    protein_menu = next(
        a.menu() for a in render_menu.actions() if a.text().replace("&", "") == "Protein"
    )
    ligand_menu = next(
        a.menu() for a in render_menu.actions() if a.text().replace("&", "") == "Ligand"
    )
    protein_styles = [a.text().replace("&", "") for a in protein_menu.actions() if a.text().strip()]
    ligand_styles = [a.text().replace("&", "") for a in ligand_menu.actions() if a.text().strip()]
    assert protein_styles == ligand_styles
    assert "Cartoon" in protein_styles
    assert "Ball and stick" in ligand_styles
    assert "Color" in protein_styles
    protein_color_menu = next(
        a.menu() for a in protein_menu.actions() if a.text().replace("&", "") == "Color"
    )
    ligand_color_menu = next(
        a.menu() for a in ligand_menu.actions() if a.text().replace("&", "") == "Color"
    )
    color_labels = [a.text().replace("&", "") for a in protein_color_menu.actions()]
    assert color_labels == [a.text().replace("&", "") for a in ligand_color_menu.actions()]
    assert "Default" in color_labels
    assert "Green" in color_labels
    dlg._on_render_style_chosen("polymer", "surface")
    dlg._on_render_style_chosen("ligand", "stick")
    assert all(r.style == "surface" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "stick" for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_render_color_chosen("ligand", "green")
    dlg._on_render_color_chosen("polymer", "cyan")
    assert all(r.color_scheme == "green" for r in dlg._rows if r.spec.kind == "ligand")
    assert all(r.color_scheme == "cyan" for r in dlg._rows if r.spec.kind == "polymer")
    payloads = dlg._component_payloads()
    lig_payload = next(p for p in payloads if p["kind"] == "ligand")
    prot_payload = next(p for p in payloads if p["kind"] == "polymer")
    assert lig_payload["carbonScheme"] == "greenCarbon"
    assert prot_payload["carbonScheme"] == "cyanCarbon"
    assert prot_payload["cartoonColor"] == "cyan"
    dlg.open_sequence_window()
    seq = dlg._sequence_dialog
    assert seq is not None
    assert seq.windowTitle() == "Sequence"
    assert seq.tabs.count() == 2
    seq.select_residue("A", "2000", "")
    assert dlg._residue_highlight
    assert dlg._residue_highlight[0]["chain"] == "A"
    captured: list[list] = []
    seq.residues_mutated.connect(captured.append)
    editor = seq._editor_at(0)
    assert editor is not None
    editor.sequence_committed.emit("S+*~")
    assert captured
    residue, letter = captured[0][0]
    assert letter == "S"
    assert residue.resn == "MET"
    dlg._act_all_atoms.setChecked(True)
    assert all(r.style == "ballstick" for r in dlg._rows if r.spec.kind == "polymer")
    dlg._act_all_atoms.setChecked(False)
    assert all(r.style == "cartoon" for r in dlg._rows if r.spec.kind == "polymer")
    seq.close()
    dlg.close()


def test_pocket_view_menu_builds_overlay(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "pocket.pdb"
    path.write_text(_POCKET_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert not dlg._act_pocket.isCheckable()
    dlg._on_pocket()
    payload = dlg._pocket_payload_data
    assert payload is not None
    assert payload["active"] is True
    assert payload["ligandSels"]
    assert any(s.get("resn") == "SER" for s in payload["residueSels"])
    assert payload["polarHPdb"]
    dlg.close()


def test_multi_file_session_and_prepare_overlay(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

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
    models = {row.spec.selection.get("model") for row in dlg._rows}
    assert models == {0, 1}
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


def test_4agc_cif_axitinib_has_carbonyl_double():
    from pathlib import Path

    import pytest
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import mol_from_cif_component

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
