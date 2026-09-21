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

"""FASTA helpers, MAFFT argv, and Protein → Sequence menu (no MAFFT binary)."""

from __future__ import annotations

from qt_helpers import qt_submenu

from pathlib import Path

from mctoolkit.platform_support import bundled_paths
from mctoolkit.protein import protein_msa
from mctoolkit.protein.protein_msa import (
    FastaRecord,
    aa_sequence_from_viewer,
    alignment_html,
    mafft_subprocess_args,
    parse_fasta,
    record_from_viewer_chain,
    records_to_clustal,
    records_to_fasta,
    run_mafft_alignment,
)


def test_aa_sequence_from_viewer_drops_heteros_and_uppercases():
    assert aa_sequence_from_viewer("Ac+*~d") == "ACD"
    assert aa_sequence_from_viewer("gGg") == "GGG"
    assert record_from_viewer_chain("A", "++~~") is None
    rec = record_from_viewer_chain("4agc_chain_A", "mkt+")
    assert rec is not None
    assert rec.sequence == "MKT"


def test_parse_fasta_headers_and_bare_blocks():
    recs = parse_fasta(">one desc\nACDE\n>two\nAC-E\n")
    assert [r.name for r in recs] == ["one desc", "two"]
    assert recs[1].sequence == "AC-E"
    bare = parse_fasta("ACDE\n\nFGHI\n")
    assert [r.sequence for r in bare] == ["ACDE", "FGHI"]


def test_mafft_subprocess_args_windows_bat(tmp_path, monkeypatch):
    monkeypatch.setattr(protein_msa.sys, "platform", "win32")
    bat = tmp_path / "mafft.bat"
    bat.write_text("", encoding="utf-8")
    fasta_in = tmp_path / "in.fa"
    fasta_in.write_text(">s1\nACDE\n", encoding="utf-8")
    argv, cwd = mafft_subprocess_args(str(bat), fasta_in, threads=4)
    assert argv[:3] == ["cmd.exe", "/c", str(bat)]
    assert argv[3:6] == ["--auto", "--amino", "--quiet"]
    assert argv[6:8] == ["--thread", "4"]
    assert argv[-1] == str(fasta_in)
    assert cwd == str(tmp_path)


def test_mafft_subprocess_args_unix_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(protein_msa.sys, "platform", "linux")
    exe = tmp_path / "mafft"
    exe.write_text("", encoding="utf-8")
    fasta_in = tmp_path / "in.fa"
    fasta_in.write_text(">s1\nACDE\n", encoding="utf-8")
    argv, cwd = mafft_subprocess_args(str(exe), fasta_in, threads=1)
    assert argv[0] == str(exe)
    assert "--thread" not in argv
    assert "--auto" in argv and "--amino" in argv
    assert cwd == str(tmp_path)


def test_run_mafft_alignment_fake_cli(tmp_path):
    def fake_runner(argv: list[str], _cwd: str | None, timeout_s: int) -> tuple[int, str, str]:
        assert "--auto" in argv
        assert "--amino" in argv
        assert timeout_s >= 1
        src = Path(argv[-1])
        recs = parse_fasta(src.read_text(encoding="utf-8"))
        width = max(len(r.sequence) for r in recs)
        aligned = [
            FastaRecord(name=r.name, sequence=r.sequence + ("-" * (width - len(r.sequence))))
            for r in recs
        ]
        return 0, records_to_fasta(aligned), ""

    out = run_mafft_alignment(
        [FastaRecord("alpha", "ACDE"), FastaRecord("beta", "ACE")],
        exe=str(tmp_path / "mafft"),
        runner=fake_runner,
    )
    assert [r.name for r in out] == ["alpha", "beta"]
    assert out[0].sequence.startswith("ACDE")
    assert "-" in out[1].sequence
    html = alignment_html(out)
    assert "<pre" in html
    clustal = records_to_clustal(out)
    assert clustal.startswith("CLUSTAL")
    assert "alpha" in clustal


def test_find_mafft_in_all_in_one_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("MCTOOLKIT_BUNDLE_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    tree = tmp_path / "mafft-win"
    tree.mkdir()
    bat = tree / "mafft.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    (tree / "usr").mkdir()
    assert bundled_paths.find_mafft_executable_in_tree(tmp_path) == bat
    assert bundled_paths.resolve_mafft_executable(str(tmp_path)) == str(bat)
    assert bundled_paths.resolve_mafft_executable(str(tree)) == str(bat)
    assert bundled_paths.resolve_mafft_executable(str(bat)) == str(bat)
    assert bundled_paths.ensure_mafft_ready(str(bat)) is None


def test_resolve_bundled_mafft_nested_folder(tmp_path, monkeypatch):
    nested = tmp_path / "mafft-win"
    nested.mkdir()
    bat = nested / "mafft.bat"
    bat.write_text("", encoding="utf-8")
    monkeypatch.setenv("MCTOOLKIT_BUNDLE_DIR", str(tmp_path))
    assert bundled_paths.resolve_bundled_executable("mafft") == bat
    assert bundled_paths.resolve_mafft_executable() == str(bat)


def test_protein_menu_has_viewer_and_sequence(qapp):  # noqa: ARG001
    from mctoolkit.ui.dialogs.protein_sequence_msa import ProteinSequenceMsaDialog
    from mctoolkit.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    protein_menu = qt_submenu(w.menuBar(), "Protein")
    labels = [a.text().replace("&", "") for a in protein_menu.actions()]
    assert "Viewer" in labels
    assert any(lab.startswith("Sequence") for lab in labels)
    assert "Dock Ligand" in labels
    dlg = w.open_protein_sequence()
    assert isinstance(dlg, ProteinSequenceMsaDialog)
    assert dlg.windowTitle() == "Protein Sequence"
    n = dlg._add_records(
        [FastaRecord("one", "ACDE"), FastaRecord("two", "ACDF")],
    )
    assert n == 2
    assert len(dlg.pool_records()) == 2
    dlg.close()
    w.close()


def test_protein_sequence_help_topic():
    from mctoolkit.ui.user_guides import guide_html

    h = guide_html("protein_sequence")
    assert "Topic unavailable" not in h
    assert "MAFFT" in h
    assert "Protein Viewer" in h
