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

"""Gnina WSL path conversion and config writing (no live gnina binary)."""

from __future__ import annotations

from mctoolkit.docking.gnina_launch import (
    convert_gnina_argv_paths,
    gnina_command_ok,
    gnina_exit_127_message,
    gnina_linux_executable,
    gnina_missing_message,
    gnina_qprocess_spec,
    resolve_gnina_command,
    write_gnina_config,
)
from mctoolkit.platform_support.wsl_launcher import windows_path_to_wsl


def test_windows_path_to_wsl_drive():
    assert windows_path_to_wsl(r"C:\tmp\rec.pdbqt") == "/mnt/c/tmp/rec.pdbqt"


def test_convert_gnina_argv_paths_rewrites_file_flags(monkeypatch):
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.linux_path",
        lambda p: windows_path_to_wsl(p),
    )
    argv = [
        "--receptor",
        r"C:\data\rec.pdbqt",
        "--ligand",
        r"C:\data\lig.sdf",
        "--out",
        r"C:\data\out.sdf",
        "--flexres",
        "A:123,A:145",
        "--flexdist_ligand",
        r"C:\data\xtal.pdb",
        "--out_flex",
        r"C:\data\out_flex.pdb",
        "--exhaustiveness",
        "8",
    ]
    converted = convert_gnina_argv_paths(argv)
    assert converted[converted.index("--receptor") + 1] == "/mnt/c/data/rec.pdbqt"
    assert converted[converted.index("--ligand") + 1] == "/mnt/c/data/lig.sdf"
    assert converted[converted.index("--out") + 1] == "/mnt/c/data/out.sdf"
    assert converted[converted.index("--flexres") + 1] == "A:123,A:145"
    assert converted[converted.index("--flexdist_ligand") + 1] == "/mnt/c/data/xtal.pdb"
    assert converted[converted.index("--out_flex") + 1] == "/mnt/c/data/out_flex.pdb"
    assert converted[converted.index("--exhaustiveness") + 1] == "8"


def test_write_gnina_config_linux_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.linux_path", lambda p: windows_path_to_wsl(p)
    )
    dest = tmp_path / "gnina.conf"
    write_gnina_config(
        [
            "--receptor",
            r"C:\data\rec.pdbqt",
            "--ligand",
            "a.sdf",
            "--out",
            r"C:\data\out.sdf",
            "--cnn_scoring",
            "rescore",
        ],
        dest,
        linux_paths=True,
    )
    text = dest.read_text(encoding="utf-8")
    assert "receptor = /mnt/c/data/rec.pdbqt" in text
    assert "out = /mnt/c/data/out.sdf" in text
    assert "cnn_scoring = rescore" in text
    assert "ligand = a.sdf" in text


def test_gnina_linux_executable_converts_windows_file():
    assert gnina_linux_executable(r"C:\Tools\gnina") == "/mnt/c/Tools/gnina"
    assert gnina_linux_executable("gnina") == "gnina"


def test_gnina_command_ok_accepts_bare_name_on_windows(monkeypatch):
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.resolve_user_executable", lambda _p: None)
    assert gnina_command_ok("gnina") is True
    assert gnina_command_ok("") is False


def test_gnina_qprocess_spec_windows_wsl_mnt_paths(monkeypatch):
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.linux_path", lambda p: windows_path_to_wsl(p)
    )
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.resolve_wsl_executable",
        lambda _p="": r"C:\Windows\System32\wsl.exe",
    )
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_ld_library_path", lambda **_k: "")
    program, args = gnina_qprocess_spec(
        "gnina",
        [
            "--receptor",
            r"C:\data\rec.pdbqt",
            "--ligand",
            r"C:\data\lig.sdf",
            "--out",
            r"C:\data\out.sdf",
        ],
        work_dir=r"C:\data",
    )
    assert program.lower().endswith("wsl.exe")
    assert "--" in args
    assert "bash" in args
    script = args[-1]
    assert "/mnt/c/data/rec.pdbqt" in script
    assert "/mnt/c/data/lig.sdf" in script
    assert "/mnt/c/data/out.sdf" in script
    assert "gnina" in script
    assert "chmod +x" not in script


def test_gnina_qprocess_spec_chmods_mnt_binary(monkeypatch):
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.linux_path", lambda p: windows_path_to_wsl(p)
    )
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.resolve_wsl_executable",
        lambda _p="": r"C:\Windows\System32\wsl.exe",
    )
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_ld_library_path", lambda **_k: "")
    program, args = gnina_qprocess_spec(
        r"C:\Tools\gnina",
        ["--receptor", r"C:\data\rec.pdbqt"],
        work_dir=r"C:\data",
    )
    assert program.lower().endswith("wsl.exe")
    script = args[-1]
    assert "chmod +x" in script
    assert "/mnt/c/Tools/gnina" in script


def test_resolve_gnina_command_uses_wsl_which(monkeypatch):
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.resolve_user_executable", lambda _p: None)
    monkeypatch.setattr(
        "mctoolkit.docking.gnina_launch.resolve_bundled_executable", lambda _t: None
    )
    monkeypatch.setattr(
        "mctoolkit.docking.gnina_launch._wsl_which",
        lambda name, timeout=20.0: "/usr/local/bin/gnina" if name == "gnina" else None,
    )
    assert resolve_gnina_command("gnina") == "/usr/local/bin/gnina"
    monkeypatch.setattr(
        "mctoolkit.docking.gnina_launch._wsl_which", lambda name, timeout=20.0: None
    )
    assert resolve_gnina_command("gnina") is None


def test_wsl_which_treats_exit_zero_as_success(monkeypatch):
    from types import SimpleNamespace

    from mctoolkit.docking.gnina_launch import _wsl_which

    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.run_linux_tool",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="/usr/local/bin/gnina\n"),
    )
    assert _wsl_which("gnina") == "/usr/local/bin/gnina"
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.run_linux_tool",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout=""),
    )
    assert _wsl_which("gnina") is None


def test_resolve_gnina_command_prefers_local_file(tmp_path, monkeypatch):
    exe = tmp_path / "gnina"
    exe.write_bytes(b"")
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr(
        "mctoolkit.docking.gnina_launch._wsl_which",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("WSL should not be probed")),
    )
    assert resolve_gnina_command(str(exe)) == str(exe)


def test_gnina_missing_message_mentions_releases():
    text = gnina_missing_message("gnina")
    assert "gnina" in text.lower()
    assert "github.com/gnina/gnina" in text


def test_gnina_exit_127_message_shared_library():
    text = gnina_exit_127_message(
        "/usr/local/bin/gnina",
        "gnina: error while loading shared libraries: libcudnn.so.9: cannot open shared object file",
    )
    assert "libcudnn.so.9" in text
    assert "cuDNN" in text
    assert "PATH" not in text


def test_gnina_qprocess_spec_exports_cuda_lib_path(monkeypatch):
    monkeypatch.setattr("mctoolkit.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.linux_path", lambda p: windows_path_to_wsl(p)
    )
    monkeypatch.setattr(
        "mctoolkit.platform_support.wsl_launcher.resolve_wsl_executable",
        lambda _p="": r"C:\Windows\System32\wsl.exe",
    )
    monkeypatch.setattr(
        "mctoolkit.docking.gnina_launch.gnina_ld_library_path",
        lambda **_k: "/home/hp/miniconda3/envs/gnina-cuda/lib",
    )
    _program, args = gnina_qprocess_spec("gnina", ["--help"], work_dir=r"C:\data")
    script = args[-1]
    assert "LD_LIBRARY_PATH=" in script
    assert "gnina-cuda/lib" in script
