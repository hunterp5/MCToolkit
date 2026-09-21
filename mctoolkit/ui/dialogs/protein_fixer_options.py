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

"""Shared PDBFixer option widgets for Fast Prepare and PDBFixer dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QWidget,
)

from ...workers.protein_prepare_constants import _DEFAULT_MAX_MISSING_GAP, _DEFAULT_WATER_CUTOFF


def add_fixer_extra_options(form: QFormLayout, host) -> None:
    """Append chain / heterogen / gap widgets to *form* and store them on *host*."""
    host.list_chains = QListWidget()
    host.list_chains.setMaximumHeight(88)
    host.list_chains.setSelectionMode(QAbstractItemView.NoSelection)
    host.list_chains.setToolTip(
        "Uncheck extra copies in the asymmetric unit. Docking usually needs one "
        "receptor chain. Leave all checked to keep every chain."
    )
    form.addRow("Keep chains:", host.list_chains)

    host.chk_skip_long_gaps = QCheckBox("Skip long missing stretches")
    host.chk_skip_long_gaps.setChecked(True)
    host.chk_skip_long_gaps.setToolTip(
        "Do not model SEQRES gaps longer than the residue limit (N-terminal tags "
        "and disordered loops). PDBFixer cannot place those stretches well; they "
        "do not help docking and can dominate minimization."
    )
    host.spin_max_gap = QSpinBox()
    host.spin_max_gap.setRange(0, 80)
    host.spin_max_gap.setValue(_DEFAULT_MAX_MISSING_GAP)
    host.spin_max_gap.setSuffix(" res")
    host.spin_max_gap.setToolTip(
        "Maximum SEQRES gap to rebuild. 6BBU’s 28-residue N-terminal tag is skipped "
        f"at the default of {_DEFAULT_MAX_MISSING_GAP}."
    )
    gap_row = QWidget()
    gap_l = QHBoxLayout(gap_row)
    gap_l.setContentsMargins(0, 0, 0, 0)
    gap_l.setSpacing(8)
    gap_l.addWidget(host.chk_skip_long_gaps, 1)
    gap_l.addWidget(host.spin_max_gap)
    form.addRow(gap_row)

    host.chk_add_missing_atoms = QCheckBox("Add missing heavy atoms in existing residues")
    host.chk_add_missing_atoms.setChecked(True)
    host.chk_add_missing_atoms.setToolTip(
        "Fill missing side-chain and terminal heavy atoms. Uncheck if a truncated "
        "residue should stay as deposited."
    )
    form.addRow(host.chk_add_missing_atoms)

    host.chk_highest_altloc = QCheckBox("Keep highest-occupancy alternate locations")
    host.chk_highest_altloc.setChecked(True)
    host.chk_highest_altloc.setToolTip(
        "When atoms have altlocs, keep the highest occupancy (ties prefer A). "
        "Uncheck to leave every alternate location in the file."
    )
    form.addRow(host.chk_highest_altloc)

    host.spin_water_cutoff = QDoubleSpinBox()
    host.spin_water_cutoff.setRange(1.0, 8.0)
    host.spin_water_cutoff.setDecimals(1)
    host.spin_water_cutoff.setSingleStep(0.5)
    host.spin_water_cutoff.setValue(_DEFAULT_WATER_CUTOFF)
    host.spin_water_cutoff.setSuffix(" Å")
    host.spin_water_cutoff.setToolTip(
        "Keep crystallographic waters whose oxygen is within this distance of a "
        "ligand heavy atom (occupancy ≥ 0.5, B ≤ 80)."
    )
    form.addRow("Water cutoff:", host.spin_water_cutoff)

    host.chk_keep_metals = QCheckBox("Keep catalytic metals")
    host.chk_keep_metals.setChecked(False)
    host.chk_keep_metals.setToolTip(
        "Keep Zn, Mg, Mn, Fe, and other metal ions. Off by default for docking; "
        "turn on for metalloenzymes."
    )
    form.addRow(host.chk_keep_metals)

    host.chk_keep_cofactors = QCheckBox("Keep cofactors (HEM, NAD, FAD, …)")
    host.chk_keep_cofactors.setChecked(False)
    host.chk_keep_cofactors.setToolTip(
        "Keep prosthetic groups when the ligand is stripped. Organic ligands are "
        "still controlled by Keep ligand."
    )
    form.addRow(host.chk_keep_cofactors)

    host.chk_strip_additives = QCheckBox("Strip crystallization additives (EDO, GOL, SO4, …)")
    host.chk_strip_additives.setChecked(True)
    host.chk_strip_additives.setToolTip(
        "Remove common crystallization buffers, glycols, and glycans even if they "
        "look like ligands. Uncheck to keep a bound sulfate or similar."
    )
    form.addRow(host.chk_strip_additives)

    host.chk_skip_long_gaps.toggled.connect(host.spin_max_gap.setEnabled)
    host.spin_max_gap.setEnabled(host.chk_skip_long_gaps.isChecked())


def populate_fixer_chain_list(host, chain_ids: tuple[str, ...] | list[str]) -> None:
    """Fill the chain list with every ID checked."""
    host.list_chains.clear()
    for cid in chain_ids:
        chain = (cid or "").strip()
        if not chain:
            continue
        item = QListWidgetItem(f"Chain {chain}")
        item.setData(Qt.UserRole, chain)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        host.list_chains.addItem(item)


def selected_fixer_chain_ids(host) -> tuple[str, ...]:
    """Return checked chain IDs, or empty when every chain is kept."""
    total = host.list_chains.count()
    if total <= 0:
        return ()
    checked: list[str] = []
    for i in range(total):
        item = host.list_chains.item(i)
        if item.checkState() == Qt.Checked:
            cid = item.data(Qt.UserRole)
            if cid:
                checked.append(str(cid))
    if not checked or len(checked) == total:
        return ()
    return tuple(checked)


def fixer_extra_request_kwargs(host) -> dict:
    """Keyword arguments for :class:`ProteinPrepareRequest` from extra widgets."""
    return {
        "skip_long_gaps": host.chk_skip_long_gaps.isChecked(),
        "max_missing_gap": int(host.spin_max_gap.value()),
        "add_missing_atoms": host.chk_add_missing_atoms.isChecked(),
        "keep_highest_occupancy_altlocs": host.chk_highest_altloc.isChecked(),
        "water_cutoff": float(host.spin_water_cutoff.value()),
        "keep_metals": host.chk_keep_metals.isChecked(),
        "keep_cofactors": host.chk_keep_cofactors.isChecked(),
        "strip_additives": host.chk_strip_additives.isChecked(),
        "keep_chain_ids": selected_fixer_chain_ids(host),
        "remove_other_heterogens": True,
    }
