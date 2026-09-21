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

"""Conformer generation core (no Qt)."""

from __future__ import annotations

import base64
import json
import threading

from rdkit import Chem

from mctoolkit.conformers.conformer_column_codec import unpack_confs_blocks_json_b64
from mctoolkit.workers import (
    ConformerGenParams,
    format_confs_table_cell,
    pack_confs_cell,
    run_conformer_generation,
)


def test_run_conformer_generation_ethanol_mmff():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=4,
        energy_window_kcal=100.0,
        force_field="MMFF",
        random_seed=7,
        prune_rms_threshold=-1.0,
        max_iterations=100,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("n_embedded", 0) >= 1
    assert out.GetNumConformers() == meta.get("n_kept")
    cell = format_confs_table_cell(meta)
    d = json.loads(cell)
    assert d["ok"] is True
    assert d["ff"] == "MMFF"
    assert len(cell) < 500

    packed = pack_confs_cell(meta, out)
    b64 = unpack_confs_blocks_json_b64(packed)
    assert b64 is not None
    blocks = json.loads(base64.b64decode(b64.encode("ascii")))
    assert isinstance(blocks, list)
    assert len(blocks) == meta.get("n_kept")


def test_run_conformer_generation_empty_mol():
    m = Chem.Mol()
    p = ConformerGenParams(
        num_confs=2, energy_window_kcal=1.0, force_field="UFF", random_seed=1, max_iterations=50
    )
    out, meta = run_conformer_generation(m, p)
    assert out is None
    assert meta.get("ok") is False
    assert "empty" in (meta.get("err") or "").lower()


def test_unpack_confs_legacy_meta_only_cell():
    cell = json.dumps({"ok": True, "n_kept": 3, "ff": "MMFF"}, separators=(",", ":"))
    assert unpack_confs_blocks_json_b64(cell) is None


def test_run_conformer_generation_single_lowest_energy():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams.single_lowest_energy(force_field="UFF", random_seed=3, max_iterations=80)
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("n_requested") == 1
    assert out.GetNumConformers() == 1
    assert meta.get("n_kept") == 1
    packed = pack_confs_cell(meta, out)
    assert unpack_confs_blocks_json_b64(packed) is not None


def test_run_conformer_generation_aligns_on_smiles():
    m = Chem.MolFromSmiles("CCc1ccccc1")
    p = ConformerGenParams(
        num_confs=8,
        energy_window_kcal=100.0,
        force_field="MMFF",
        random_seed=5,
        max_iterations=80,
        align_pattern="c1ccccc1",
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("n_align_atoms") == 6
    assert meta.get("align_pattern") == "c1ccccc1"
    assert out.GetNumConformers() >= 2
    assert float(meta.get("rms_max", 1.0)) < 0.05


def test_run_conformer_generation_align_pattern_not_found():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=4,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=1,
        max_iterations=50,
        align_pattern="c1ccccc1",
    )
    out, meta = run_conformer_generation(m, p)
    assert out is None
    assert meta.get("err") == "align_pattern_not_found"


def test_run_conformer_generation_invalid_align_pattern():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=3,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=1,
        max_iterations=40,
        align_pattern="[[[notsmarts",
        align_pattern_is_smarts=True,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is None
    assert meta.get("err") == "invalid_align_pattern"


def test_run_conformer_generation_cancelled_before_work():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=4,
        energy_window_kcal=100.0,
        force_field="MMFF",
        random_seed=7,
        prune_rms_threshold=-1.0,
        max_iterations=50,
    )
    ev = threading.Event()
    ev.set()
    out, meta = run_conformer_generation(m, p, cancel_event=ev)
    assert out is None
    assert meta.get("err") == "cancelled"


def test_run_conformer_generation_mmff94s():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams(
        num_confs=3,
        energy_window_kcal=100.0,
        force_field="MMFF94s",
        random_seed=7,
        max_iterations=80,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("ff") in ("MMFF94s", "UFF")
    assert out.GetNumConformers() >= 1


def test_run_conformer_generation_max_keep():
    m = Chem.MolFromSmiles("CCCC")
    p = ConformerGenParams(
        num_confs=8,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=11,
        max_iterations=40,
        max_keep=2,
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("max_keep") == 2
    assert out.GetNumConformers() <= 2
    assert meta.get("n_kept") == out.GetNumConformers()


def test_run_conformer_generation_post_min_rms_prunes():
    m = Chem.MolFromSmiles("CCCC")
    wide = ConformerGenParams(
        num_confs=12,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=13,
        max_iterations=40,
    )
    tight = ConformerGenParams(
        num_confs=12,
        energy_window_kcal=100.0,
        force_field="UFF",
        random_seed=13,
        max_iterations=40,
        post_min_rms_threshold=2.0,
    )
    out_w, meta_w = run_conformer_generation(m, wide)
    out_t, meta_t = run_conformer_generation(m, tight)
    assert out_w is not None and out_t is not None
    assert meta_t.get("ok") is True
    assert float(meta_t.get("post_min_rms_A") or 0) == 2.0
    assert int(meta_t.get("n_after_rms_prune") or 0) <= int(meta_t.get("n_after_ewin") or 0)
    assert int(meta_t.get("n_kept") or 0) <= int(meta_w.get("n_kept") or 0)


def test_run_conformer_generation_keep_hydrogens():
    m = Chem.MolFromSmiles("CCO")
    p = ConformerGenParams.single_lowest_energy(
        force_field="UFF", random_seed=3, max_iterations=80, keep_hydrogens=True
    )
    out, meta = run_conformer_generation(m, p)
    assert out is not None
    assert meta.get("ok") is True
    assert meta.get("keep_hs") is True
    assert any(a.GetAtomicNum() == 1 for a in out.GetAtoms())
