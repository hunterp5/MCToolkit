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
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Bundled resource and external tool path resolution."""

from __future__ import annotations

from pathlib import Path

from molmanager import bundled_paths


def test_default_external_executable_falls_back_to_name(monkeypatch, tmp_path):
    monkeypatch.setenv("MOLMANAGER_BUNDLE_DIR", str(tmp_path))
    assert bundled_paths.default_external_executable("smina") in ("smina", "smina.exe")


def test_default_obabel_uses_pip_wheel(monkeypatch, tmp_path):
    monkeypatch.setenv("MOLMANAGER_BUNDLE_DIR", str(tmp_path))
    pip_exe = bundled_paths.pip_openbabel_executable()
    got = bundled_paths.default_external_executable("obabel")
    if pip_exe is None:
        assert Path(got).name.lower() in {"obabel", "obabel.exe"}
    else:
        assert got == str(pip_exe)
        assert pip_exe.is_file()


def test_resolve_user_executable(tmp_path):
    missing = tmp_path / "missing.bin"
    assert bundled_paths.resolve_user_executable(str(missing)) is None
    assert bundled_paths.resolve_user_executable("") is None
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    assert bundled_paths.resolve_user_executable(str(exe)) == str(exe)


def test_resolve_user_executable_bare_name_uses_bundle(tmp_path, monkeypatch):
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("MOLMANAGER_BUNDLE_DIR", str(tmp_path))
    assert bundled_paths.resolve_user_executable("smina.exe") == str(exe)
    assert bundled_paths.resolve_user_executable("smina") == str(exe)


def test_resolve_bundled_executable_when_present(tmp_path, monkeypatch):
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("MOLMANAGER_BUNDLE_DIR", str(tmp_path))
    assert bundled_paths.resolve_bundled_executable("smina") == exe
    assert bundled_paths.default_external_executable("smina") == str(exe)


def test_smina_launch_env_sets_babel_libdir(tmp_path):
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    (tmp_path / "formats_common.obf").write_bytes(b"")
    data = tmp_path / "data"
    data.mkdir()
    (data / "atomtyp.txt").write_text("C\n", encoding="utf-8")
    env = bundled_paths.smina_launch_env(str(exe))
    assert env["BABEL_LIBDIR"] == str(tmp_path)
    assert env["BABEL_DATADIR"] == str(data)
    assert bundled_paths.openbabel_launch_env(str(exe)) == env


def test_apply_openbabel_runtime_env_points_at_uff_prm(monkeypatch):
    import os

    import pytest

    pip_exe = bundled_paths.pip_openbabel_executable()
    if pip_exe is None:
        pytest.skip("openbabel wheel not installed")
    monkeypatch.setenv(
        "BABEL_DATADIR", str(pip_exe.parent.parent / "share" / "openbabel" / "3.2.1")
    )
    env = bundled_paths.apply_openbabel_runtime_env()
    assert env
    data = Path(env["BABEL_DATADIR"])
    assert (data / "UFF.prm").is_file()
    assert os.environ.get("BABEL_DATADIR") == str(data)
    assert Path(env["BABEL_LIBDIR"]).is_dir()


def test_smina_launch_env_empty_without_plugins(tmp_path):
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    assert bundled_paths.smina_launch_env(str(exe)) == {}


def test_static_asset_path_points_at_3dmol():
    p = bundled_paths.static_asset_path("3Dmol-min.js")
    assert p.name == "3Dmol-min.js"
    assert p.parent.name == "static"
    assert Path(bundled_paths.package_root(), "ui", "static", "3Dmol-min.js") == p


def test_resolve_biotransformer_jar_env_override_and_missing_database(tmp_path, monkeypatch):
    monkeypatch.delenv("MOLMANAGER_BIOTRANSFORMER_JAR", raising=False)
    monkeypatch.setattr(bundled_paths, "biotransformer_models_dir", lambda: tmp_path / "absent")
    assert bundled_paths.resolve_biotransformer_jar() is None
    jar = tmp_path / "biotransformer-3.0.0.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("MOLMANAGER_BIOTRANSFORMER_JAR", str(jar))
    assert bundled_paths.resolve_biotransformer_jar() == jar
    errs = bundled_paths.biotransformer_layout_errors(jar)
    assert any("database/" in e for e in errs)
    (tmp_path / "database").mkdir()
    (tmp_path / "supportfiles").mkdir()
    layout = bundled_paths.biotransformer_layout_errors(jar)
    assert not any("database/" in e or "supportfiles/" in e for e in layout)
