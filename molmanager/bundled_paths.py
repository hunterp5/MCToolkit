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

"""Resolve bundled resources and optional external tool executables."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent

# Basenames searched under ``resources/bin/<platform>/`` (first match wins).
_TOOL_BINARIES: dict[str, tuple[str, ...]] = {
    "smina": ("smina.exe", "smina"),
    "obabel": ("obabel.exe", "obabel"),
}


def package_root() -> Path:
    return _PACKAGE_ROOT


def resources_dir() -> Path:
    return _PACKAGE_ROOT / "resources"


def _platform_bin_subdir() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def bundled_bin_dir() -> Path:
    override = (os.environ.get("MOLMANAGER_BUNDLE_DIR") or "").strip()
    if override:
        return Path(override)
    return resources_dir() / "bin" / _platform_bin_subdir()


def resolve_bundled_executable(tool: str) -> Path | None:
    """Return an executable path when shipped under ``resources/bin/<platform>/``."""
    key = (tool or "").strip().lower()
    names = _TOOL_BINARIES.get(key)
    if not names:
        return None
    base = bundled_bin_dir()
    if not base.is_dir():
        return None
    for name in names:
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def pip_openbabel_executable() -> Path | None:
    """``obabel`` shipped inside the pip ``openbabel`` wheel (``site-packages/openbabel/bin``)."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("openbabel")
    except (ImportError, ValueError):
        return None
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin:
        return None
    root = Path(origin).resolve().parent
    for name in _TOOL_BINARIES.get("obabel", ("obabel.exe", "obabel")):
        candidate = root / "bin" / name
        if candidate.is_file():
            return candidate
    return None


def _interpreter_scripts_executable(names: tuple[str, ...]) -> Path | None:
    """Look next to the current Python (venv ``Scripts`` / conda prefix)."""
    bindir = Path(sys.executable).resolve().parent
    search = (bindir, bindir / "Scripts")
    for directory in search:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def default_external_executable(tool: str) -> str:
    """
    Prefer a bundled binary, then a pip/venv install, otherwise the bare tool name.

    Set ``MOLMANAGER_BUNDLE_DIR`` to point at a directory containing platform binaries.
    """
    bundled = resolve_bundled_executable(tool)
    if bundled is not None:
        return str(bundled)
    key = (tool or "").strip().lower()
    names = _TOOL_BINARIES.get(key)
    if key == "obabel":
        pip_exe = pip_openbabel_executable()
        if pip_exe is not None:
            return str(pip_exe)
    if names:
        scripts_exe = _interpreter_scripts_executable(names)
        if scripts_exe is not None:
            return str(scripts_exe)
        if sys.platform.startswith("win"):
            return names[0]
        return names[-1]
    return tool


def resolve_user_executable(user_path: str) -> str | None:
    """Return an existing executable path from a file path or PATH name, else ``None``."""
    text = (user_path or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_file():
        return str(candidate)
    from shutil import which

    found = which(text)
    if found:
        return found
    if sys.platform.startswith("win") and not text.lower().endswith(".exe"):
        found = which(f"{text}.exe")
        if found:
            return found
    if candidate.parent == Path("."):
        bundled = resolve_bundled_executable(candidate.stem)
        if bundled is not None:
            return str(bundled)
    return None


def _openbabel_plugin_dir(exe_dir: Path) -> Path | None:
    """Directory containing OpenBabel format plugins (``.obf`` or ``*.so``)."""
    if any(exe_dir.glob("*.obf")):
        return exe_dir
    nested = exe_dir / "openbabel"
    if nested.is_dir() and any(nested.glob("*.obf")):
        return nested
    lib_ob = exe_dir.parent.parent / "lib" / "openbabel"
    if lib_ob.is_dir():
        if any(lib_ob.glob("*.so")) or any(lib_ob.glob("*.obf")):
            return lib_ob
        for sub in sorted(lib_ob.glob("*")):
            if sub.is_dir() and (any(sub.glob("*.so")) or any(sub.glob("*.obf"))):
                return sub
    return None


def _openbabel_data_dir(exe_dir: Path) -> Path | None:
    """Directory containing OpenBabel data files (``atomtyp.txt``)."""
    for candidate in (
        exe_dir / "data",
        exe_dir / "openbabel-data",
        exe_dir.parent.parent / "share" / "openbabel",
    ):
        if (candidate / "atomtyp.txt").is_file():
            return candidate
    return None


def openbabel_launch_env(exe: str) -> dict[str, str]:
    """
    Environment so Open Babel can load format plugins and data files.

    Conda-forge Open Babel (and Smina linked against it) needs ``BABEL_LIBDIR``
    pointing at the ``.obf`` plugins, otherwise format I/O fails even when files exist.
    """
    text = (exe or "").strip()
    if not text:
        return {}
    exe_path = Path(text).expanduser()
    exe_dir = exe_path.parent if exe_path.is_file() else Path(text).expanduser().parent
    if not exe_dir.is_dir():
        return {}
    env: dict[str, str] = {}
    plugin_dir = _openbabel_plugin_dir(exe_dir)
    if plugin_dir is not None:
        env["BABEL_LIBDIR"] = str(plugin_dir)
    data_dir = _openbabel_data_dir(exe_dir)
    if data_dir is not None:
        env["BABEL_DATADIR"] = str(data_dir)
    return env


def apply_openbabel_runtime_env(obabel_path: str = "") -> dict[str, str]:
    """
    Write ``BABEL_DATADIR`` / ``BABEL_LIBDIR`` into ``os.environ`` for this process.

    The pip wheel's ``openbabel/__init__.py`` overwrites those variables on import
    with ``share/openbabel/<ver>`` and ``lib/openbabel/<ver>``. On Windows wheels
    the force-field files (``UFF.prm``, ``mmff94.ff``) and ``*.obf`` plugins live
    under ``openbabel/bin/data`` and ``openbabel/bin`` instead, so Confab then
    fails with ``Cannot open UFF.prm``. Call this after importing Open Babel.
    """
    exe = ""
    text = (obabel_path or "").strip()
    if text:
        exe = resolve_user_executable(text) or ""
    if not exe:
        pip_exe = pip_openbabel_executable()
        if pip_exe is not None:
            exe = str(pip_exe)
    if not exe:
        exe = resolve_user_executable(default_external_executable("obabel")) or ""
    if not exe:
        return {}
    env = openbabel_launch_env(exe)
    if env:
        os.environ.update(env)
    return env


def smina_launch_env(exe: str) -> dict[str, str]:
    """Environment so Smina's OpenBabel can load format plugins and data files."""
    return openbabel_launch_env(exe)


def models_dir() -> Path:
    return resources_dir() / "models"


def gnn_mtl_model_path() -> Path:
    """GNN-MTL Chemprop checkpoint (``model.pt``) from Zenodo 10.5281/zenodo.16948542."""
    override = (os.environ.get("MOLMANAGER_GNN_MTL_MODEL") or "").strip()
    if override:
        return Path(override)
    return models_dir() / "gnn_mtl" / "model.pt"


def static_asset_path(name: str) -> Path:
    """Path to a file under ``molmanager/ui/static`` (e.g. ``3Dmol-min.js``)."""
    return _PACKAGE_ROOT / "ui" / "static" / name
