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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Modeless BioTransformer results browser: parent structure plus metabolite table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QShortcut,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...biotransformer import BIOTRANSFORMER_CANCELLED
from ...display_constants import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ...structure_draw import render_molecule_png
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_METABOLITES
from ..widgets import NumericTableWidgetItem

_THUMB_W = 120
_THUMB_H = 100


@dataclass(frozen=True)
class MetaboliteBrowseHit:
    smiles: str
    reaction: str = ""
    enzyme: str = ""
    biosystem: str = ""
    generation: int | None = None
    precursor_smiles: str = ""


@dataclass(frozen=True)
class MetaboliteBrowseRecord:
    """One parent molecule and its predicted metabolites."""

    oid: int | None
    smiles: str
    metabolites: tuple[MetaboliteBrowseHit, ...] = ()
    error: str | None = None
    columns: dict[str, str] = field(default_factory=dict)


def _coerce_hit(item: Any) -> MetaboliteBrowseHit | None:
    if isinstance(item, MetaboliteBrowseHit):
        return item
    if isinstance(item, dict):
        smi = str(item.get("smiles") or "").strip()
        if not smi:
            return None
        gen = item.get("generation")
        try:
            generation = int(gen) if gen is not None and str(gen).strip() != "" else None
        except (TypeError, ValueError):
            generation = None
        return MetaboliteBrowseHit(
            smiles=smi,
            reaction=str(item.get("reaction") or ""),
            enzyme=str(item.get("enzyme") or ""),
            biosystem=str(item.get("biosystem") or ""),
            generation=generation,
            precursor_smiles=str(item.get("precursor_smiles") or ""),
        )
    return None


def records_from_worker_rows(rows: Sequence) -> list[MetaboliteBrowseRecord]:
    """Convert Predict Metabolites worker tuples into browser records."""
    out: list[MetaboliteBrowseRecord] = []
    for row in rows or ():
        if not row:
            continue
        oid = row[0]
        cols = dict(row[1] or {})
        hits_raw = row[2] if len(row) > 2 else ()
        parent_smi = str(row[5] if len(row) > 5 else "") or ""
        hits = tuple(h for h in (_coerce_hit(x) for x in (hits_raw or ())) if h is not None)
        err = None
        if not hits:
            err = str(cols.get("Metabolite Reactions") or "").strip() or None
            if err in {"N/A", ""}:
                err = "No metabolites were returned."
        rec = MetaboliteBrowseRecord(
            oid=None if oid is None else int(oid),
            smiles=parent_smi,
            metabolites=hits,
            error=err if not hits else None,
            columns=cols,
        )
        if rec.error == BIOTRANSFORMER_CANCELLED and not rec.metabolites:
            continue
        out.append(rec)
    return out


def _pixmap_from_smiles(smiles: str, width: int, height: int) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    try:
        png = render_molecule_png(mol, int(width), int(height))
    except Exception:
        return None
    pm = QPixmap.fromImage(QImage.fromData(png))
    return None if pm.isNull() else pm


class MetaboliteBrowserDialog(QDialog):
    """Step through parent molecules and inspect BioTransformer products."""

    def __init__(self, parent_app=None, parent: QWidget | None = None):
        super().__init__(parent if parent is not None else parent_app)
        self.parent_app = parent_app
        self.setWindowTitle(f"{TOOL_PREDICT_METABOLITES} Browser")
        self.setMinimumWidth(max(480, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH))
        self.setMinimumHeight(max(420, BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT + 180))
        self._records: list[MetaboliteBrowseRecord] = []
        self._idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self._meta = QLabel("")
        self._prev = QPushButton("←")
        self._next = QPushButton("→")
        self._prev.clicked.connect(lambda: self._step(-1))
        self._next.clicked.connect(lambda: self._step(1))
        nav.addWidget(self._prev)
        nav.addWidget(self._next)
        nav.addWidget(self._meta, 1)
        root.addLayout(nav)

        self._parent_img = QLabel()
        self._parent_img.setAlignment(Qt.AlignCenter)
        self._parent_img.setMinimumSize(
            BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2,
            BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2,
        )
        self._parent_img.setStyleSheet("background: palette(base);")
        root.addWidget(self._parent_img, 1)

        self._parent_smiles = QLabel("")
        self._parent_smiles.setWordWrap(True)
        self._parent_smiles.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._parent_smiles)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["#", "Structure", "SMILES", "Reaction", "Enzyme", "Step"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        root.addWidget(self._table, 2)

        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self._step(1))
        make_window_minimizable(self)

    def set_records(self, records: list[MetaboliteBrowseRecord]) -> None:
        self._records = list(records or [])
        self._idx = 0
        self._update_ui()

    def jump_to_oid(self, oid: int | None) -> bool:
        if oid is None:
            return False
        want = int(oid)
        for i, rec in enumerate(self._records):
            if rec.oid == want:
                self._idx = i
                self._update_ui()
                return True
        return False

    def _step(self, delta: int) -> None:
        if not self._records:
            return
        self._idx = (self._idx + int(delta)) % len(self._records)
        self._update_ui()

    def _current(self) -> MetaboliteBrowseRecord | None:
        if not self._records or not (0 <= self._idx < len(self._records)):
            return None
        return self._records[self._idx]

    def _update_ui(self) -> None:
        rec = self._current()
        n = len(self._records)
        row_txt = ""
        if rec is not None and rec.oid is not None:
            row_txt = f"  (row {rec.oid})"
        self._meta.setText(f"{TOOL_PREDICT_METABOLITES}: {self._idx + 1} / {max(n, 1)}{row_txt}")
        self._prev.setEnabled(n > 1)
        self._next.setEnabled(n > 1)
        if rec is None:
            self._parent_img.setPixmap(QPixmap())
            self._parent_smiles.setText("No metabolite results.")
            self._table.setRowCount(0)
            return
        pm = _pixmap_from_smiles(
            rec.smiles,
            BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
            BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
        )
        if pm is None:
            self._parent_img.setPixmap(QPixmap())
            self._parent_img.setText(rec.error or "Could not draw parent.")
        else:
            self._parent_img.setText("")
            self._parent_img.setPixmap(pm)
        self._parent_smiles.setText(rec.smiles or rec.error or "")
        hits = rec.metabolites
        self._table.setRowCount(len(hits))
        for i, hit in enumerate(hits):
            num = NumericTableWidgetItem(str(i + 1))
            num.setData(Qt.EditRole, i + 1)
            self._table.setItem(i, 0, num)
            thumb = QLabel()
            thumb.setAlignment(Qt.AlignCenter)
            tpm = _pixmap_from_smiles(hit.smiles, _THUMB_W, _THUMB_H)
            if tpm is not None:
                thumb.setPixmap(tpm)
            self._table.setCellWidget(i, 1, thumb)
            self._table.setItem(i, 2, QTableWidgetItem(hit.smiles))
            self._table.setItem(i, 3, QTableWidgetItem(hit.reaction))
            self._table.setItem(i, 4, QTableWidgetItem(hit.enzyme))
            step = "" if hit.generation is None else str(hit.generation)
            step_item = NumericTableWidgetItem(step)
            if hit.generation is not None:
                step_item.setData(Qt.EditRole, int(hit.generation))
            self._table.setItem(i, 5, step_item)
            self._table.setRowHeight(i, _THUMB_H + 8)
        if rec.error and not hits:
            self._parent_smiles.setText(rec.error)
