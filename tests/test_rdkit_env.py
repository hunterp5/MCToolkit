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

"""RDKit version gate used at desktop startup."""

from __future__ import annotations

import importlib.metadata

import pytest

from molmanager.rdkit_env import (
    MIN_RDKIT_VERSION,
    parse_rdkit_version,
    require_supported_rdkit,
    unsupported_rdkit_message,
)


def test_parse_rdkit_version_zero_padded_and_short():
    assert parse_rdkit_version("2022.09.5") == (2022, 9, 5)
    assert parse_rdkit_version("2025.9.1") == (2025, 9, 1)
    assert parse_rdkit_version("2026.03.6") == (2026, 3, 6)
    assert parse_rdkit_version("2025_09_1") == (2025, 9, 1)


def test_require_supported_rdkit_accepts_installed_build():
    require_supported_rdkit()


def test_require_supported_rdkit_rejects_old_build(monkeypatch):
    monkeypatch.setattr(
        "molmanager.rdkit_env.rdkit_version_tuple",
        lambda: (2022, 9, 5),
    )
    with pytest.raises(RuntimeError, match=r"imported 2022\.9\.5"):
        require_supported_rdkit()


def test_unsupported_message_mentions_rdkit_pypi_when_installed(monkeypatch):
    monkeypatch.setattr(
        "molmanager.rdkit_env._rdkit_pypi_is_installed",
        lambda: True,
    )
    msg = unsupported_rdkit_message("2022.09.5")
    assert "rdkit-pypi" in msg
    assert "shadows" in msg
    required = ".".join(str(part) for part in MIN_RDKIT_VERSION)
    assert required in msg


def test_rdkit_pypi_detection_uses_importlib(monkeypatch):
    def _missing(_name: str):
        raise importlib.metadata.PackageNotFoundError("rdkit-pypi")

    monkeypatch.setattr("molmanager.rdkit_env.importlib.metadata.distribution", _missing)
    from molmanager.rdkit_env import _rdkit_pypi_is_installed

    assert _rdkit_pypi_is_installed() is False
