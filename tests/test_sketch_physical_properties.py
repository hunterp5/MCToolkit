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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Physical properties helpers for the sketcher View panel."""

from __future__ import annotations

from qt_helpers import qt_submenu
from PySide6.QtWidgets import QMenuBar, QWidget
from rdkit import Chem

from mctoolkit.ui.sketcher.constants import (
    ELEMENT_FAMILY_GROUPS,
    SKETCH_ELEMENT_SYMBOLS,
)
from mctoolkit.ui.sketcher.customize_elements import (
    element_groups_for_symbols,
    normalize_toolbar_element_symbols,
)
from mctoolkit.ui.sketcher.dialog import SketcherDialog
from mctoolkit.ui.sketcher.physical_properties import (
    compute_rdkit_physical_properties,
    compute_sketch_physical_properties,
)


def test_compute_rdkit_physical_properties_ethanol() -> None:
    mol = Chem.MolFromSmiles("CCO")
    props = compute_rdkit_physical_properties(mol)
    assert props.error is None
    assert props.mw is not None and abs(props.mw - 46.069) < 0.05
    assert props.tpsa is not None and props.tpsa > 15.0
    assert props.logp is not None
    assert props.qed is not None and 0.0 <= props.qed <= 1.0
    assert props.ro5_pass == "Yes"
    assert props.ro5_violations == 0
    assert props.logd is None
    assert props.pka_values is None


def test_compute_rdkit_physical_properties_empty() -> None:
    props = compute_rdkit_physical_properties(None)
    assert props.error == "empty"


def test_compute_ionization_failure_when_no_microstates(monkeypatch) -> None:
    monkeypatch.setattr(
        "mctoolkit.ui.sketcher.physical_properties.predict_microstates_for_sketch",
        lambda _mol, cancel_event=None: None,
    )
    mol = Chem.MolFromSmiles("CCN")
    props = compute_sketch_physical_properties(mol, with_ionization=True)
    assert props.mw is not None
    assert props.error == "pKa calculation failed"
    assert props.logd is None
    assert props.pka_values is None
    assert props.ab_mps is None
    assert props.cns_mpo is None


def test_compute_ionization_properties_raises_without_microstates(monkeypatch) -> None:
    from mctoolkit.ui.sketcher.physical_properties import compute_ionization_properties

    monkeypatch.setattr(
        "mctoolkit.ui.sketcher.physical_properties.predict_microstates_for_sketch",
        lambda _mol, cancel_event=None: None,
    )
    mol = Chem.MolFromSmiles("CCO")
    try:
        compute_ionization_properties(mol)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "pKa" in str(exc)


def test_normalize_toolbar_element_symbols() -> None:
    out = normalize_toolbar_element_symbols(["au", "C", "N", "C"])
    assert out[0] == "C"
    assert "N" in out
    assert "Au" in out
    assert out.count("C") == 1


def test_element_groups_for_symbols_by_family() -> None:
    groups = dict(element_groups_for_symbols(["C", "Au", "N", "Rb", "Gd", "Sn"]))
    assert groups["Carbon Group"] == ("C", "Sn")
    assert groups["Pnictogens"] == ("N",)
    assert groups["Alkali Metals"] == ("Rb",)
    assert groups["Transition Metals"] == ("Au",)
    assert groups["Lanthanides"] == ("Gd",)
    assert "Other" not in groups


def test_element_family_groups_cover_sketch_symbols() -> None:
    covered = {sym for _title, syms in ELEMENT_FAMILY_GROUPS for sym in syms}
    assert set(SKETCH_ELEMENT_SYMBOLS) == covered


def test_physical_properties_view_action(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    bars = dlg.findChildren(QMenuBar)
    assert bars
    menus = {title: qt_submenu(bars[0], title.replace("&", "")) for title in ("View", "Settings")}
    assert "Physical Properties" in [a.text() for a in menus["View"].actions() if a.text()]
    assert "Customize Elements" in [a.text() for a in menus["Settings"].actions() if a.text()]
    dlg._open_physical_properties()
    assert dlg._phys_props_dlg is not None
    assert dlg._phys_props_dlg.isVisible()
    assert not hasattr(dlg._phys_props_dlg, "_val_smiles")
    dlg._phys_props_dlg.close()
    dlg.close()


def test_populate_element_toolbar_subset(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    dlg._populate_element_toolbar(["C", "N", "O", "Au"])
    assert set(dlg._element_btn_by_symbol) == {"C", "N", "O", "Au"}
    assert dlg.tb_wildcard is not None
    assert dlg.tb_any_element is not None
    groups = dict(element_groups_for_symbols(["C", "N", "O", "Au"]))
    assert groups["Transition Metals"] == ("Au",)
    dlg.close()
