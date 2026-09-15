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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_DESCRIPTOR_TAB_ORDER = (
    "Physiochemical",
    "Fingerprints",
    "Name",
    "Drug-likeness",
    "Structural Counts",
    "Ring Counts",
    "Atom Counts",
    "Complexity",
    "Electronic",
)

_NAME_DESCRIPTOR_ORDER = (
    "SMILES String",
    "InChI Key",
    "Molecular formula",
)

_PHYSICOCHEMICAL_DESCRIPTOR_ORDER = (
    "Fraction CSP3",
    "Labute ASA",
    "LogD 7.4",
    "LogP",
    "LogS intrinsic (ESOL)",
    "LogS 7.4",
    "Mol Weight",
    "Molar Refractivity",
    "TPSA",
)

from ...science_citations import descriptor_checkbox_citation_html
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class PropertyDialog(QDialog):
    def __init__(self, columns, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calculate Descriptors")
        self.setMinimumWidth(780)
        self.resize(820, 700)
        self._have_selection = selected_row_count > 0
        l = QVBoxLayout(self)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target Column:"))
        self.src_combo = QComboBox()
        self.src_combo.addItems([c for c in columns if (c or "").strip()])
        target_row.addWidget(self.src_combo, 1)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        target_row.addWidget(self.only_selected_cb, 0, Qt.AlignVCenter)
        l.addLayout(target_row)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(True)

        categories = {
            "Physiochemical": {
                "Fraction CSP3": "FractionCSP3",
                "Labute ASA": "LabuteASA",
                "LogD 7.4": "LOGD74",
                "LogP": "MolLogP",
                "LogS intrinsic (ESOL)": "LOGS_ESOL",
                "LogS 7.4": "LOGS74",
                "Mol Weight": "MolWt",
                "Molar Refractivity": "MolMR",
                "TPSA": "TPSA",
            },
            "Name": {
                "SMILES String": "SMILES",
                "InChI Key": "INCHIKEY",
                "Molecular formula": "MOLFORMULA",
            },
            "Drug-likeness": {
                "QED Score": "QED",
                "AB-MPS score": "AB_MPS",
                "Ro5 violations": "RO5_VIOLATIONS",
                "Ro5 pass": "RO5_PASS",
                "CNS MPO score": "CNS_MPO",
            },
            "Structural Counts": {
                "Heavy Atoms": "HeavyAtomCount",
                "NH/OH Count": "NumNHOH",
                "NO Count": "NumNO",
                "Heteroatoms": "NumHeteroatoms",
                "H-Bond Donors": "NumHDonors",
                "H-Bond Acceptors": "NumHAcceptors",
                "Rotatable Bonds": "NumRotatableBonds",
                "Valence Electrons": "NumValenceElectrons",
            },
            "Ring Counts": {
                "Total Rings": "RingCount",
                "Aromatic Rings": "NumAromaticRings",
                "Saturated Rings": "NumSaturatedRings",
                "Aliphatic Rings": "NumAliphaticRings",
                "Spiro Atoms": "NumSpiroAtoms",
                "Bridgehead Atoms": "NumBridgeheadAtoms",
            },
            "Atom Counts": {
                "Carbons": "Count_C",
                "Nitrogens": "Count_N",
                "Oxygens": "Count_O",
                "Fluorines": "Count_F",
                "Chlorines": "Count_Cl",
                "Bromines": "Count_Br",
                "Iodines": "Count_I",
                "Sulfurs": "Count_S",
                "Phosphorus": "Count_P",
            },
            "Complexity": {
                "Bertz Complexity": "BertzCT",
                "Balaban J": "BalabanJ",
                "Hall-Kier Alpha": "HallKierAlpha",
                "Kappa 1": "Kappa1",
                "Kappa 2": "Kappa2",
            },
            "Electronic": {
                "Net Formal Charge": "NET_FORMAL_CHARGE",
                "Max Partial Charge": "MaxPartialCharge",
                "Min Partial Charge": "MinPartialCharge",
                "Max Abs Partial Charge": "MaxAbsPartialCharge",
                "Min Abs Partial Charge": "MinAbsPartialCharge",
            },
        }

        from ...rdkit_fingerprints import descriptor_fingerprint_categories

        categories["Fingerprints"] = descriptor_fingerprint_categories()

        self.cbs = {}
        for cat_name in _DESCRIPTOR_TAB_ORDER:
            props = categories.get(cat_name)
            if not props:
                continue
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            tab = QWidget()
            tab_lyt = QVBoxLayout(tab)
            if cat_name == "Physiochemical":
                ordered_items = [
                    (disp, props[disp])
                    for disp in _PHYSICOCHEMICAL_DESCRIPTOR_ORDER
                    if disp in props
                ]
            elif cat_name == "Name":
                ordered_items = [
                    (disp, props[disp]) for disp in _NAME_DESCRIPTOR_ORDER if disp in props
                ]
            else:
                ordered_items = sorted(props.items(), key=lambda kv: kv[0].casefold())
            for disp, internal in ordered_items:
                row = QHBoxLayout()
                row.setSpacing(8)
                cb = QCheckBox(disp)
                row.addWidget(cb, 0, Qt.AlignTop)
                cite_html = descriptor_checkbox_citation_html(internal)
                if cite_html:
                    cite_lbl = QLabel(f"<small>{cite_html}</small>")
                    cite_lbl.setWordWrap(True)
                    cite_lbl.setTextFormat(Qt.RichText)
                    cite_lbl.setOpenExternalLinks(True)
                    cite_lbl.setStyleSheet("color: palette(mid);")
                    row.addWidget(cite_lbl, 1, Qt.AlignVCenter)
                else:
                    row.addStretch(1)
                tab_lyt.addLayout(row)
                self.cbs[disp] = (cb, internal)
            tab_lyt.addStretch()
            scroll.setWidget(tab)
            self.tabs.addTab(scroll, cat_name)

        l.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        l.addWidget(bb)
        make_window_minimizable(self)

    def get_selected(self):
        sel_disp, sel_int = [], []
        for d, (cb, i) in self.cbs.items():
            if cb.isChecked():
                sel_disp.append(d)
                sel_int.append(i)
        return sel_disp, sel_int

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)
