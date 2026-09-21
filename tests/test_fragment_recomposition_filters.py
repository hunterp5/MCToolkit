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

"""Tests for BRICS / RECAP recomposition generation constraints."""

import threading

import pytest
from rdkit import Chem

from mctoolkit.chem.fragment_decomposition import decompose_brics, recompose_fragments
from mctoolkit.chem.fragment_recomposition_filters import (
    filter_product_smiles,
    parse_recomposition_filter_text,
    product_passes_filters,
)
from mctoolkit.workers.fragment_recomposition import FragmentRecompositionWorker
from mctoolkit.workers.signals import WorkerSignals


def test_parse_recomposition_filter_text_range_and_comparisons():
    rules = parse_recomposition_filter_text("MW 200-500, LogP <= 5, HeavyAtoms >= 10")
    assert len(rules) == 3
    assert rules[0].property_key == "MolWt"
    assert rules[0].op == "range"
    assert rules[1].property_key == "MolLogP"
    assert rules[1].op == "lte"
    assert rules[2].property_key == "HeavyAtomCount"
    assert rules[2].op == "gte"


def test_filter_product_smiles_by_molecular_weight():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    products, _skipped, _cancelled = recompose_fragments(
        frags, "brics", max_depth=2, max_products=50
    )
    assert products

    kept, filtered = filter_product_smiles(products, "MW <= 500")
    assert kept
    assert filtered >= 0
    assert len(kept) + filtered == len(products)

    for smi in kept:
        m = Chem.MolFromSmiles(smi)
        assert m is not None
        assert product_passes_filters(m, parse_recomposition_filter_text("MW <= 500"))


def test_filter_product_smiles_rejects_all_when_impossible():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    products, _skipped, _cancelled = recompose_fragments(
        frags, "brics", max_depth=2, max_products=50
    )
    kept, filtered = filter_product_smiles(products, "MW < 1")
    assert kept == []
    assert filtered == len(products)


def test_recompose_fragments_applies_constraints_during_generation():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    products, skipped, cancelled = recompose_fragments(
        frags,
        "brics",
        max_depth=2,
        max_products=50,
        output_filters="MW <= 500",
    )
    assert not cancelled
    assert products
    rules = parse_recomposition_filter_text("MW <= 500")
    for smi in products:
        m = Chem.MolFromSmiles(smi)
        assert m is not None
        assert product_passes_filters(m, rules)
    assert skipped >= 0


def test_recompose_fragments_raises_when_no_constraint_matches():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    with pytest.raises(ValueError, match="generation constraints"):
        recompose_fragments(
            frags,
            "brics",
            max_depth=2,
            max_products=50,
            output_filters="MW < 1",
        )


def test_recompose_fragments_max_products_counts_accepted_only():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    products, _skipped, cancelled = recompose_fragments(
        frags,
        "brics",
        max_depth=2,
        max_products=3,
        output_filters="MW <= 500",
    )
    assert not cancelled
    assert len(products) <= 3


def test_recompose_fragments_honours_cancel_event():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    cancel = threading.Event()
    cancel.set()
    products, skipped, cancelled = recompose_fragments(
        frags,
        "brics",
        max_depth=3,
        max_products=2000,
        output_filters="MW <= 500",
        cancel_event=cancel,
    )
    assert cancelled
    assert products == []
    assert skipped == 0


def test_fragment_recomposition_worker_emits_cancelled_without_finish():
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.fragment_recomp_finished.connect(
        lambda products, title, skipped: out.update({"finished": (products, title, skipped)})
    )
    sigs.fragment_recomp_failed.connect(lambda msg, title: out.update({"failed": (msg, title)}))
    cancel = threading.Event()
    cancel.set()
    worker = FragmentRecompositionWorker(
        frags,
        "brics",
        2,
        50,
        "BRICS Recomposition",
        sigs,
        output_filters="MW <= 500",
        cancel_event=cancel,
    )
    worker.run()
    assert out.get("failed") == ("Cancelled.", "BRICS Recomposition")
    assert "finished" not in out


def test_fragment_recomposition_worker_appends_partial_products_on_cancel(monkeypatch):
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    frags = decompose_brics(mol)
    partial = ["CCO", "CCN"]

    def _fake_recompose(*_args, **_kwargs):
        return list(partial), 12, True

    monkeypatch.setattr(
        "mctoolkit.workers.fragment_recomposition.recompose_fragments",
        _fake_recompose,
    )
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.partial_results.connect(
        lambda label, done, total: out.update({"partial": (label, done, total)})
    )
    sigs.fragment_recomp_finished.connect(
        lambda products, title, skipped: out.update({"finished": (list(products), title, skipped)})
    )
    sigs.fragment_recomp_failed.connect(lambda msg, title: out.update({"failed": (msg, title)}))
    worker = FragmentRecompositionWorker(
        frags,
        "recap",
        2,
        50,
        "RECAP Recomposition",
        sigs,
        cancel_event=threading.Event(),
    )
    worker.run()
    assert out.get("partial") == ("RECAP Recomposition", 2, 50)
    assert out.get("finished") == (partial, "RECAP Recomposition", 12)
    assert out.get("failed") == ("Cancelled.", "RECAP Recomposition")
