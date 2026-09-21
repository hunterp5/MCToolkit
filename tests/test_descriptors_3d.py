# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Scalar 3D descriptors (shape, SASA, volume) and packed-confs coordinate lookup."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from mctoolkit.conformers.conformer_column_codec import pack_confs_cell
from mctoolkit.descriptors.descriptors_3d import (
    DESCRIPTOR_3D_ITEMS,
    DESCRIPTOR_3D_KEYS,
    int_fns_need_3d,
    mol_for_3d_descriptors,
)
from mctoolkit.workers.chemistry_descriptors import (
    _calc_descriptor_row_values,
    descriptor_callable_for_int_fn,
)


def _ethanol_2d():
    mol = Chem.MolFromSmiles("CCO")
    AllChem.Compute2DCoords(mol)
    return mol


def _phenethylamine_3d():
    mol = Chem.MolFromSmiles("c1ccccc1CCN")
    mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, randomSeed=1) == 0
    AllChem.UFFOptimizeMolecule(mol)
    return mol


def test_int_fns_need_3d():
    assert int_fns_need_3d(("MolWt", "PMI1"))
    assert int_fns_need_3d(("SASA",))
    assert not int_fns_need_3d(("MolWt", "QED"))
    assert not int_fns_need_3d(())


def test_mol_for_3d_descriptors_rejects_2d():
    assert mol_for_3d_descriptors(_ethanol_2d()) is None
    assert mol_for_3d_descriptors(Chem.MolFromSmiles("CCO")) is None


def test_mol_for_3d_descriptors_from_embedded_mol():
    work = mol_for_3d_descriptors(_phenethylamine_3d())
    assert work is not None
    assert work.GetNumConformers() == 1


def test_mol_for_3d_descriptors_prefers_packed_confs():
    packed_mol = _phenethylamine_3d()
    cell = pack_confs_cell({"ok": True, "n_kept": 1, "n_packed": 1}, packed_mol)
    work = mol_for_3d_descriptors(_ethanol_2d(), packed_cell=cell)
    assert work is not None
    assert work.GetNumHeavyAtoms() >= 9


def _atom0_xyz(mol: Chem.Mol, cid: int | None = None) -> tuple[float, float, float]:
    conf = mol.GetConformer() if cid is None else mol.GetConformer(int(cid))
    p = conf.GetAtomPosition(0)
    return (float(p.x), float(p.y), float(p.z))


def test_mol_for_3d_descriptors_picks_lowest_energy_not_first_id():
    mol = _phenethylamine_3d()
    good = Chem.Conformer(mol.GetConformer())
    bad = Chem.Conformer(mol.GetConformer())
    p0 = bad.GetAtomPosition(0)
    bad.SetAtomPosition(0, (float(p0.x) + 3.0, float(p0.y), float(p0.z)))
    mol.RemoveAllConformers()
    mol.AddConformer(bad, assignId=True)
    mol.AddConformer(good, assignId=True)
    assert mol.GetNumConformers() == 2
    work = mol_for_3d_descriptors(mol)
    assert work is not None
    assert work.GetNumConformers() == 1
    kept = _atom0_xyz(work)
    gx = float(good.GetAtomPosition(0).x)
    gy = float(good.GetAtomPosition(0).y)
    gz = float(good.GetAtomPosition(0).z)
    bx = float(bad.GetAtomPosition(0).x)
    by = float(bad.GetAtomPosition(0).y)
    bz = float(bad.GetAtomPosition(0).z)
    good_xyz = (gx, gy, gz)
    bad_xyz = (bx, by, bz)

    def _dist(a, b) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    assert _dist(kept, good_xyz) < 0.05
    assert _dist(kept, bad_xyz) > 1.0
    cell = pack_confs_cell({"ok": True, "n_kept": 2, "n_packed": 2}, mol)
    packed_work = mol_for_3d_descriptors(_ethanol_2d(), packed_cell=cell)
    assert packed_work is not None
    assert _dist(_atom0_xyz(packed_work), good_xyz) < 0.05


def test_3d_descriptor_values_on_embedded_mol():
    mol3 = mol_for_3d_descriptors(_phenethylamine_3d())
    assert mol3 is not None
    oid, row = _calc_descriptor_row_values(
        1,
        _ethanol_2d(),
        ["PMI 1", "NPR 1", "SASA", "Molecular volume", "PBF"],
        ("PMI1", "NPR1", "SASA", "MolVolume", "PBF"),
        {},
        pka_states=None,
        pka_cache_used=False,
        mol_3d=mol3,
    )
    assert oid == 1
    pmi1 = float(row["PMI 1"])
    npr1 = float(row["NPR 1"])
    sasa = float(row["SASA"])
    vol = float(row["Molecular volume"])
    pbf = float(row["PBF"])
    assert pmi1 > 0.0
    assert 0.0 < npr1 < 1.0
    assert sasa > 50.0
    assert vol > 50.0
    assert pbf >= 0.0


def test_3d_descriptors_na_without_coordinates():
    oid, row = _calc_descriptor_row_values(
        2,
        _ethanol_2d(),
        ["PMI 1", "Mol Weight"],
        ("PMI1", "MolWt"),
        {},
        pka_states=None,
        pka_cache_used=False,
    )
    assert oid == 2
    assert row["PMI 1"] == "N/A"
    assert float(row["Mol Weight"]) > 40.0


def test_3d_descriptors_from_packed_cell_without_2d_mol():
    packed_mol = _phenethylamine_3d()
    cell = pack_confs_cell({"ok": True, "n_kept": 1, "n_packed": 1}, packed_mol)
    oid, row = _calc_descriptor_row_values(
        3,
        None,
        ["NPR 2"],
        ("NPR2",),
        {},
        pka_states=None,
        pka_cache_used=False,
        packed_confs=cell,
    )
    assert oid == 3
    assert 0.0 < float(row["NPR 2"]) <= 1.0


def test_descriptor_callable_3d_requires_ctx_mol():
    fn = descriptor_callable_for_int_fn("PMI1", {})
    try:
        fn(_ethanol_2d())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError without mol_3d")


def test_all_3d_keys_have_dialog_items_and_fns():
    from mctoolkit.descriptors.descriptors_3d import DESCRIPTOR_3D_FNS

    assert {k for _d, k in DESCRIPTOR_3D_ITEMS} == DESCRIPTOR_3D_KEYS
    assert set(DESCRIPTOR_3D_FNS) == DESCRIPTOR_3D_KEYS


def test_packed_confs_from_ingest_structure_column(qapp):  # noqa: ARG001
    from mctoolkit.storage import ensemble_mol_for
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.table.setColumnHidden(0, True)
    mol3d = _phenethylamine_3d()
    oid = w.next_oid
    w.next_oid += 1
    cells = w._ingest_store_mol(oid, mol3d)
    w._table_model.append_row(oid, cells)
    packed, cols, db = w._ensemble_inputs_for_descriptor_job([oid], "Structure")
    assert oid in cols
    ens = ensemble_mol_for(db, oid, cols[oid], min_conformers=1)
    assert ens is not None
    work = mol_for_3d_descriptors(ens, packed_cell=packed.get(oid))
    assert work is not None
    oid_out, row = _calc_descriptor_row_values(
        oid,
        w.mols[oid],
        ["PMI 1"],
        ("PMI1",),
        {},
        pka_states=None,
        pka_cache_used=False,
        mol_3d=work,
    )
    assert oid_out == oid
    assert float(row["PMI 1"]) > 0.0
    w.close()


def test_property_dialog_3d_tab(qapp) -> None:  # noqa: ARG001
    from PySide6.QtWidgets import QLabel

    from mctoolkit.ui.dialogs.properties import PropertyDialog

    dlg = PropertyDialog(["Structure", "SMILES"], selected_row_count=0)
    assert "PMI 1" in dlg.cbs
    assert dlg.cbs["PMI 1"][1] == "PMI1"
    assert "SASA" in dlg.cbs
    assert dlg.cbs["Molecular volume"][1] == "MolVolume"
    labels = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert "3D" in labels
    scroll = dlg.tabs.widget(labels.index("3D"))
    tab = scroll.widget()
    assert tab.findChildren(QLabel) == []
    assert "3D" in dlg.cbs["PMI 1"][0].toolTip()
    dlg.cbs["PMI 1"][0].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["PMI 1"]
    assert fns == ["PMI1"]
    dlg.close()
