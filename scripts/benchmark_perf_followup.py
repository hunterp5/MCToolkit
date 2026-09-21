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

"""A/B microbenchmarks for the Sep 2026 performance follow-up.

Compares the previous implementations against the current code for:

* uncompressed SDF (SDMolSupplier index vs ForwardSDMolSupplier)
* MOL2 (full-file read vs record streaming)
* EnsembleStore (commit-per-write vs batched commits)
* Butina clustering (dense float64 matrix vs fingerprints only)
* SQL load (accumulate all rows vs page-sized lists)

Usage:
    python scripts/benchmark_perf_followup.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem
from rdkit.Geometry import Point3D

from mctoolkit.platform_support.memory_usage import current_process_rss_bytes, format_memory_bytes
from mctoolkit.storage.ensemble_store import EnsembleStore
from mctoolkit.table.table_file_formats import _MOL2_MARKER, iter_mol2_mols, iter_sdf_mols
from mctoolkit.workers.cluster_worker import (
    _dense_fingerprint_matrix,
    cluster_butina,
)

N_MOLS = 4000
N_ENSEMBLE = 2000
N_SQL = 20_000
N_CLUSTER = 1500


def _ethanol_mol2() -> str:
    return (
        f"{_MOL2_MARKER}\n"
        "ethanol\n 3 2 0 0 0\nSMALL\nNO_CHARGES\n\n"
        "@<TRIPOS>ATOM\n"
        "      1 C1          0.0000    0.0000    0.0000 C.3       1  LIG  0.0000\n"
        "      2 C2          1.5000    0.0000    0.0000 C.3       1  LIG  0.0000\n"
        "      3 O3          2.0000    1.2000    0.0000 O.3       1  LIG  0.0000\n"
        "@<TRIPOS>BOND\n"
        "     1     1     2    1\n"
        "     2     2     3    1\n"
    )


def _write_sdf(path: Path, n: int) -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    writer = Chem.SDWriter(str(path))
    for _ in range(n):
        writer.write(mol)
    writer.close()


def _write_mol2(path: Path, n: int) -> None:
    path.write_text(_ethanol_mol2() * n, encoding="utf-8")


def _timed(fn):
    t0 = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - t0) * 1000.0
    return result, ms


def _rss() -> str:
    n = current_process_rss_bytes()
    return format_memory_bytes(n) if n is not None else "n/a"


def _report(title: str, old_ms: float, new_ms: float, extra: str = "") -> None:
    speedup = old_ms / new_ms if new_ms > 0 else float("inf")
    delta = old_ms - new_ms
    print(
        f"{title:28s}  old {old_ms:8.1f} ms  new {new_ms:8.1f} ms  "
        f"{speedup:5.2f}x  saved {delta:8.1f} ms  {extra}"
    )


def bench_sdf(tmp: Path) -> None:
    path = tmp / "lib.sdf"
    _write_sdf(path, N_MOLS)

    def old() -> tuple[int, float]:
        t_first = None
        n = 0
        t0 = time.perf_counter()
        for mol in Chem.SDMolSupplier(str(path)):
            if mol is None:
                continue
            if t_first is None:
                t_first = (time.perf_counter() - t0) * 1000.0
            n += 1
        return n, t_first or 0.0

    def new() -> tuple[int, float]:
        t_first = None
        n = 0
        t0 = time.perf_counter()
        for mol in iter_sdf_mols(path):
            if t_first is None:
                t_first = (time.perf_counter() - t0) * 1000.0
            n += 1
        return n, t_first or 0.0

    (n_old, first_old), old_ms = _timed(old)
    (n_new, first_new), new_ms = _timed(new)
    assert n_old == n_new == N_MOLS
    _report(
        f"SDF iterate {N_MOLS}",
        old_ms,
        new_ms,
        extra=f"first-mol old {first_old:.1f} ms new {first_new:.1f} ms",
    )


def bench_mol2(tmp: Path) -> None:
    path = tmp / "lib.mol2"
    _write_mol2(path, N_MOLS)

    def old() -> int:
        text = path.read_text(encoding="utf-8")
        n = 0
        for chunk in text.split(_MOL2_MARKER)[1:]:
            mol = Chem.MolFromMol2Block(_MOL2_MARKER + chunk)
            if mol is not None:
                n += 1
        return n

    def new() -> int:
        return sum(1 for _ in iter_mol2_mols(path))

    tracemalloc.start()
    n_old, old_ms = _timed(old)
    _, old_peak = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    n_new, new_ms = _timed(new)
    _, new_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n_old == n_new == N_MOLS
    _report(
        f"MOL2 iterate {N_MOLS}",
        old_ms,
        new_ms,
        extra=(
            f"peak alloc old {format_memory_bytes(old_peak)} new {format_memory_bytes(new_peak)}"
        ),
    )


def _packed_ethanol() -> Chem.Mol:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(0.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(1.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(2.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    return mol


def bench_ensemble() -> None:
    mol = _packed_ethanol()

    def old() -> int:
        store = EnsembleStore()
        try:
            for i in range(N_ENSEMBLE):
                store.store_mol(i, "confs", mol)
                store.flush()
            return len(store)
        finally:
            store.close()

    def new() -> int:
        store = EnsembleStore()
        try:
            for i in range(N_ENSEMBLE):
                store.store_mol(i, "confs", mol)
            return len(store)
        finally:
            store.close()

    n_old, old_ms = _timed(old)
    n_new, new_ms = _timed(new)
    assert n_old == n_new == N_ENSEMBLE
    _report(f"EnsembleStore write {N_ENSEMBLE}", old_ms, new_ms)


def bench_butina() -> None:
    smis = ["CCO", "CCCO", "CCCCO", "c1ccccc1", "Cc1ccccc1", "c1ccncc1"]
    mols = [Chem.MolFromSmiles(s) for s in smis]
    fps = [
        AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048)
        for m in mols
        for _ in range(N_CLUSTER // len(mols))
    ]

    def old() -> int:
        X = _dense_fingerprint_matrix(fps)
        labels = cluster_butina(fps, 0.35)
        return int(X.nbytes) if labels is not None else 0

    def new() -> int:
        labels = cluster_butina(fps, 0.35)
        return 0 if labels is None else int(labels.nbytes)

    n_old, old_ms = _timed(old)
    n_new, new_ms = _timed(new)
    _report(
        f"Butina n={len(fps)}",
        old_ms,
        new_ms,
        extra=f"dense matrix {format_memory_bytes(n_old)} vs labels {format_memory_bytes(n_new)}",
    )
    _ = DataStructs.BulkTanimotoSimilarity(fps[0], fps[:2])


def bench_sql(tmp: Path) -> None:
    db = tmp / "load.sqlite"
    con = sqlite3.connect(str(db))
    try:
        con.execute("CREATE TABLE compounds (SMILES TEXT, Name TEXT)")
        con.executemany(
            "INSERT INTO compounds VALUES (?, ?)",
            [("CCO", f"row_{i}") for i in range(N_SQL)],
        )
        con.commit()
    finally:
        con.close()

    from mctoolkit.workers.sql_load_worker import SqlLoadParseResult, SqlLoadSignals, SqlLoadWorker

    url = "sqlite:///" + str(db).replace("\\", "/")

    def accumulate() -> int:
        from sqlalchemy import create_engine, text

        from mctoolkit.workers.sql_load_worker import cells_from_sql_mapping, mol_blob_from_smiles

        prepared = []
        blobs = {}
        eng = create_engine(url)
        try:
            with eng.connect() as conn:
                rs = conn.execution_options(stream_results=True).execute(
                    text("SELECT * FROM compounds")
                )
                cols = [str(c) for c in rs.keys()]
                oid = 0
                while True:
                    recs = rs.fetchmany(512)
                    if not recs:
                        break
                    for rec in recs:
                        cells = cells_from_sql_mapping(cols, rec._mapping)
                        prepared.append((oid, cells))
                        blob = mol_blob_from_smiles(cells.get("SMILES", ""))
                        if blob:
                            blobs[oid] = blob
                        oid += 1
                rs.close()
        finally:
            eng.dispose()
        return len(prepared) + len(blobs)

    def stream() -> int:
        class Collector:
            def __init__(self) -> None:
                self.n = 0
                self.max_page = 0

            def on_chunk(self, result: SqlLoadParseResult) -> None:
                self.max_page = max(self.max_page, len(result.prepared_rows))
                self.n += len(result.prepared_rows)

        collector = Collector()
        errors: list[str] = []
        signals = SqlLoadSignals()
        signals.chunk.connect(collector.on_chunk)
        signals.finished.connect(lambda *_a: None)
        signals.failed.connect(errors.append)
        SqlLoadWorker(
            url=url,
            engine_kwargs={},
            sql="SELECT * FROM compounds",
            page_size=512,
            limit_eff=0,
            apply_limit=False,
            signals=signals,
            generation=1,
        ).run()
        if errors:
            raise RuntimeError(errors[0])
        return collector.n * 1000 + collector.max_page

    tracemalloc.start()
    n_old, old_ms = _timed(accumulate)
    _, old_peak = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    packed, new_ms = _timed(stream)
    _, new_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    n_new, max_page = divmod(packed, 1000)
    assert n_old // 2 == n_new == N_SQL
    _report(
        f"SQL parse {N_SQL}",
        old_ms,
        new_ms,
        extra=(
            f"peak alloc old {format_memory_bytes(old_peak)} "
            f"new {format_memory_bytes(new_peak)}  max page {max_page}"
        ),
    )


def main() -> None:
    print(f"RSS start {_rss()}")
    with tempfile.TemporaryDirectory(prefix="mctoolkit_perf_") as raw:
        tmp = Path(raw)
        bench_sdf(tmp)
        bench_mol2(tmp)
        bench_ensemble()
        bench_butina()
        bench_sql(tmp)
    print(f"RSS end   {_rss()}")


if __name__ == "__main__":
    main()
