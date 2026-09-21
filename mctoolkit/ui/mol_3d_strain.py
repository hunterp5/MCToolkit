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

"""Strain-energy table filling for the ligand 3D viewer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget

from .widgets import NumericTableWidgetItem


_STRAIN_TABLE_BASE_HEADERS = (
    "Conf",
    "E",
    "ΔE vs ref",
    "ΔE vs min",
    "Pop. %",
    "RMSD",
)

_STRAIN_FF_COLUMN_ORDER = ("MMFF", "MMFF94s", "UFF")


def _fmt_strain_kcal(value) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""


def populate_strain_energy_table(table: QTableWidget, overlay: dict | None) -> int:
    """Fill a results table with one row per conformer. Returns the row count."""
    table.setSortingEnabled(False)
    table.clearContents()
    table.setRowCount(0)
    if not isinstance(overlay, dict):
        table.setColumnCount(len(_STRAIN_TABLE_BASE_HEADERS))
        table.setHorizontalHeaderLabels(list(_STRAIN_TABLE_BASE_HEADERS))
        return 0
    energies = list(overlay.get("energies") or [])
    n = len(energies)
    deltas = list(overlay.get("deltas") or [])
    deltas_min = list(overlay.get("deltas_min") or [])
    pop_fracs = list(overlay.get("pop_fracs") or [])
    rmsds = list(overlay.get("rmsds") or [])
    primary_ff = str(overlay.get("ff") or "").strip()
    by_ff = overlay.get("energies_by_ff") if isinstance(overlay.get("energies_by_ff"), dict) else {}
    extra_ffs = [
        name
        for name in _STRAIN_FF_COLUMN_ORDER
        if name != primary_ff and isinstance(by_ff.get(name), list) and len(by_ff[name]) == n
    ]
    headers = list(_STRAIN_TABLE_BASE_HEADERS)
    for name in extra_ffs:
        headers.append(f"E ({name})")
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    if n <= 0:
        return 0

    def _at(seq: list, i: int):
        return seq[i] if i < len(seq) else None

    for i in range(n):
        table.insertRow(i)
        conf_item = NumericTableWidgetItem()
        conf_item.setData(Qt.EditRole, float(i + 1))
        conf_item.setText(str(i + 1))
        conf_item.setData(Qt.UserRole, int(i))
        table.setItem(i, 0, conf_item)

        e_item = NumericTableWidgetItem()
        e_item.setData(Qt.EditRole, float(energies[i]))
        e_item.setText(_fmt_strain_kcal(energies[i]))
        table.setItem(i, 1, e_item)

        d_ref = _at(deltas, i)
        d_item = NumericTableWidgetItem()
        if d_ref is None:
            d_item.setText("")
        else:
            d_item.setData(Qt.EditRole, float(d_ref))
            d_item.setText(_fmt_strain_kcal(d_ref))
        table.setItem(i, 2, d_item)

        d_min = _at(deltas_min, i)
        dm_item = NumericTableWidgetItem()
        if d_min is None:
            dm_item.setText("")
        else:
            dm_item.setData(Qt.EditRole, float(d_min))
            dm_item.setText(_fmt_strain_kcal(d_min))
        table.setItem(i, 3, dm_item)

        pop = _at(pop_fracs, i)
        p_item = NumericTableWidgetItem()
        if pop is None:
            p_item.setText("")
        else:
            pct = 100.0 * float(pop)
            p_item.setData(Qt.EditRole, pct)
            p_item.setText(f"{pct:.1f}")
        table.setItem(i, 4, p_item)

        rms = _at(rmsds, i)
        r_item = NumericTableWidgetItem()
        if rms is None:
            r_item.setText("")
        else:
            r_item.setData(Qt.EditRole, float(rms))
            r_item.setText(_fmt_strain_kcal(rms))
        table.setItem(i, 5, r_item)

        for col_i, name in enumerate(extra_ffs, start=6):
            vals = by_ff.get(name) or []
            extra = NumericTableWidgetItem()
            if i < len(vals):
                extra.setData(Qt.EditRole, float(vals[i]))
                extra.setText(_fmt_strain_kcal(vals[i]))
            table.setItem(i, col_i, extra)

    table.setSortingEnabled(True)
    return n
