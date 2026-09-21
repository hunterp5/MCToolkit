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

"""AmberTools GAFF/GAFF2 helpers for Protein Prepare."""

from __future__ import annotations

from mctoolkit.workers.protein_prepare_amber import (
    _ligand_ff_is_gaff,
    _ligand_ff_tag,
    _normalize_ligand_ff,
    leap_input,
)


def test_normalize_ligand_ff_aliases() -> None:
    assert _normalize_ligand_ff("GAFF2") == "gaff2"
    assert _normalize_ligand_ff("gaff-2.11") == "gaff2"
    assert _normalize_ligand_ff("gaff") == "gaff"
    assert _normalize_ligand_ff("") == "none"
    assert _normalize_ligand_ff("protein") == "none"
    assert _ligand_ff_is_gaff("gaff2")
    assert _ligand_ff_is_gaff("gaff")
    assert not _ligand_ff_is_gaff("none")
    assert _ligand_ff_tag("gaff2") == "GAFF2"
    assert _ligand_ff_tag("gaff") == "GAFF"
    assert _ligand_ff_tag("none") == ""


def test_leap_input_gaff2_ff14sb_gbn2() -> None:
    text = leap_input(
        protein_pdb="protein_leap.pdb",
        ligands=[("lig0_gaff.mol2", "lig0.frcmod", "AXI")],
        protein_ff="amber14",
        ligand_ff="gaff2",
        keep_water=False,
        solvent="gbn2",
        prmtop="complex.prmtop",
        inpcrd="complex.inpcrd",
    )
    assert "source leaprc.protein.ff14SB" in text
    assert "source leaprc.gaff2" in text
    assert "leaprc.water.tip3p" not in text
    assert "set default PBradii mbondi3" in text
    assert "loadamberparams lig0.frcmod" in text
    assert "LIG0 = loadMol2 lig0_gaff.mol2" in text
    assert "PROT = loadPdb protein_leap.pdb" in text
    assert "COMP = combine { PROT LIG0 }" in text
    assert "saveAmberParm COMP complex.prmtop complex.inpcrd" in text
    assert "solvateBox" not in text


def test_leap_input_solvate_box_and_ions() -> None:
    text = leap_input(
        protein_pdb="protein_leap.pdb",
        ligands=[("lig0_gaff.mol2", "lig0.frcmod", "AXI")],
        protein_ff="amber14",
        ligand_ff="gaff2",
        keep_water=False,
        solvent="gbn2",
        prmtop="complex.prmtop",
        inpcrd="complex.inpcrd",
        receptor_prmtop="receptor.prmtop",
        receptor_inpcrd="receptor.inpcrd",
        ligand_prmtop="ligand.prmtop",
        ligand_inpcrd="ligand.inpcrd",
        solvated_prmtop="solvated.prmtop",
        solvated_inpcrd="solvated.inpcrd",
        solvate_padding_a=10.0,
        ion_conc_m=0.15,
    )
    assert "source leaprc.water.tip3p" in text
    assert "set default PBradii mbondi3" in text
    assert "saveAmberParm COMP complex.prmtop complex.inpcrd" in text
    assert "solvateBox COMP TIP3PBOX 10.0" in text
    assert "addIonsRand COMP Na+ 0 Cl- 0 0.15" in text
    assert "saveAmberParm COMP solvated.prmtop solvated.inpcrd" in text
    dry_at = text.index("saveAmberParm COMP complex.prmtop")
    box_at = text.index("solvateBox")
    solv_at = text.index("saveAmberParm COMP solvated.prmtop")
    assert dry_at < box_at < solv_at


def test_leap_input_gaff_ff99_water_obc2() -> None:
    text = leap_input(
        protein_pdb="prot.pdb",
        ligands=[("a_gaff.mol2", "a.frcmod", "LIG"), ("b_gaff.mol2", "b.frcmod", "LG2")],
        protein_ff="amber99sbildn",
        ligand_ff="gaff",
        keep_water=True,
        solvent="obc2",
        prmtop="c.prmtop",
        inpcrd="c.inpcrd",
    )
    assert "source oldff/leaprc.ff99SBildn" in text
    assert "source leaprc.gaff\n" in text
    assert "source leaprc.water.tip3p" in text
    assert "set default PBradii mbondi2" in text
    assert "combine { PROT LIG0 LIG1 }" in text


def test_leap_input_vacuum_skips_pbradii() -> None:
    text = leap_input(
        protein_pdb="prot.pdb",
        ligands=[("lig0_gaff.mol2", "lig0.frcmod", "LIG")],
        protein_ff="amber14",
        ligand_ff="gaff2",
        keep_water=False,
        solvent="vacuum",
        prmtop="c.prmtop",
        inpcrd="c.inpcrd",
    )
    assert "PBradii" not in text


def test_relabel_amber_histidines_hie_with_hd1_becomes_hid() -> None:
    from mctoolkit.workers.protein_prepare_amber import relabel_amber_histidines_pdb

    pdb = """\
ATOM      1  ND1 HIE A 869       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  HD1 HIE A 869       0.000   0.000   1.000  1.00  0.00           H
ATOM      3  NE2 HIE A 869       1.000   0.000   0.000  1.00  0.00           N
ATOM      4  CA  ALA A 870       2.000   0.000   0.000  1.00  0.00           C
END
"""
    out = relabel_amber_histidines_pdb(pdb)
    assert "HID A 869" in out
    assert "HIE A 869" not in out
    assert "ALA A 870" in out


def test_relabel_amber_histidines_keeps_hie_and_promotes_hip() -> None:
    from mctoolkit.workers.protein_prepare_amber import relabel_amber_histidines_pdb

    pdb = """\
ATOM      1  NE2 HIE A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  HE2 HIE A   1       0.000   0.000   1.000  1.00  0.00           H
ATOM      3  ND1 HIS A   2       1.000   0.000   0.000  1.00  0.00           N
ATOM      4  HD1 HIS A   2       1.000   0.000   1.000  1.00  0.00           H
ATOM      5  NE2 HIS A   2       2.000   0.000   0.000  1.00  0.00           N
ATOM      6  HE2 HIS A   2       2.000   0.000   1.000  1.00  0.00           H
END
"""
    out = relabel_amber_histidines_pdb(pdb)
    assert "HIE A   1" in out
    assert "HIP A   2" in out
    assert "HIS A   2" not in out


def test_run_linux_tool_wsl_login_shell(monkeypatch, tmp_path) -> None:
    from mctoolkit.platform_support.wsl_launcher import run_linux_tool

    captured: dict = {}

    def _run_wsl(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs

        class _Proc:
            returncode = 0
            stdout = "/usr/bin/antechamber\n"
            stderr = ""

        return _Proc()

    monkeypatch.setattr("mctoolkit.platform_support.wsl_launcher.sys.platform", "win32")
    monkeypatch.setattr("mctoolkit.platform_support.wsl_launcher.run_wsl", _run_wsl)
    work = tmp_path / "amber"
    work.mkdir()
    proc = run_linux_tool(["antechamber", "-i", "lig.mol2"], work_dir=work, timeout=12.0)
    assert proc.returncode == 0
    assert captured["args"][0] == "bash"
    assert captured["args"][1] == "-lic"
    script = captured["args"][2]
    assert "antechamber" in script
    assert "lig.mol2" in script
    assert captured["kwargs"]["timeout"] == 12.0


def test_ambertools_available_false_when_which_fails(monkeypatch) -> None:
    from mctoolkit.workers import protein_prepare_amber as amber

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.run_linux_tool", lambda *_a, **_k: _Proc()
    )
    assert amber.ambertools_available() is False


def test_build_gaff_prmtop_requires_ambertools(monkeypatch, tmp_path) -> None:
    from mctoolkit.workers.protein_prepare_amber import build_gaff_prmtop

    monkeypatch.setattr(
        "mctoolkit.workers.protein_prepare_amber.ambertools_available", lambda **_k: False
    )
    pdb = tmp_path / "holo.pdb"
    pdb.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n")
    try:
        build_gaff_prmtop(
            pdb,
            ligand_mols=[object()],
            ligand_keys={("A", "1", "")},
            keep_water=False,
            protein_ff="amber14",
            ligand_ff="gaff2",
            solvent="gbn2",
            work_dir=tmp_path,
        )
    except RuntimeError as exc:
        assert "AmberTools" in str(exc)
        assert "antechamber" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
