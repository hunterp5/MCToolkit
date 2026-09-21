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

"""Standalone demo for CompoundTableModel + CompoundTableView."""

from __future__ import annotations


def run_table_model_demo() -> int:
    """Small window demonstrating the model + view + sort + pixmap update."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMainWindow,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from .ui.compound_table_model import CompoundTableModel
    from .ui.compound_table_view import CompoundTableView

    app = QApplication.instance() or QApplication([])

    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    model = CompoundTableModel(headers)
    for i in range(8):
        smi = "C" * (i + 1)
        model.append_row(oid=100 + i, cells={"SMILES": smi, "MW": str(50 + i * 13)})

    w = QMainWindow()
    w.setWindowTitle("MCToolkit — QAbstractTableModel prototype")
    cw = QWidget()
    ly = QVBoxLayout(cw)
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resizeColumnsToContents()
    ly.addWidget(
        QLabel(
            "Click a column header to select that column; Shift+click another header to select a range. "
            "Right-click the header for Sort (numeric or alphabetic). "
            "Structure column shows placeholders until you click the button."
        )
    )
    ly.addWidget(view)

    def fake_render():
        for oid in model.all_oids_in_order():
            pm = QPixmap(120, 90)
            pm.fill(QColor(240, 248, 255))
            p = QPainter(pm)
            p.setPen(Qt.darkGray)
            p.drawText(pm.rect(), Qt.AlignCenter, f"id {oid}")
            p.end()
            model.set_structure_pixmap(oid, pm)

    btn = QPushButton("Simulate 2D render (placeholder pixmap per row)")
    btn.clicked.connect(fake_render)
    ly.addWidget(btn)
    w.setCentralWidget(cw)
    w.resize(900, 520)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_table_model_demo())
