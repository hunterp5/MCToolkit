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

"""One-time RDKit runtime tweaks for the desktop app (logging noise, etc.)."""

from __future__ import annotations

import importlib.metadata
import logging

from ..app_identity import APP_DISPLAY_NAME

logger = logging.getLogger(__name__)

# Keep in sync with rdkit>=… in pyproject.toml / requirements*.txt.
MIN_RDKIT_VERSION = (2025, 9, 1)

_CONFIGURED = False


def parse_rdkit_version(version: str) -> tuple[int, int, int]:
    """Parse ``2025.09.1`` / ``2025.9.1`` style RDKit version strings."""
    parts: list[int] = []
    for token in version.replace("_", ".").split("."):
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        if digits:
            parts.append(int(digits))
        if len(parts) >= 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def rdkit_version_tuple() -> tuple[int, int, int]:
    from rdkit import rdBase

    raw = getattr(rdBase, "rdkitVersion", "") or getattr(rdBase, "rdkitBuild", "")
    return parse_rdkit_version(str(raw))


def _rdkit_pypi_is_installed() -> bool:
    try:
        importlib.metadata.distribution("rdkit-pypi")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def unsupported_rdkit_message(version: str) -> str:
    """Human-readable install hint when the imported RDKit is too old."""
    required = ".".join(str(part) for part in MIN_RDKIT_VERSION)
    lines = [
        f"{APP_DISPLAY_NAME} requires RDKit {required} or newer; this environment imported {version}.",
        "Install the official PyPI package named 'rdkit' (not 'rdkit-pypi', which stopped at 2022.9.5):",
        "  pip uninstall rdkit-pypi",
        "  pip install -r requirements.txt",
        "Use this project's .venv rather than a global conda/base Python that has other chemistry tools.",
    ]
    if _rdkit_pypi_is_installed():
        lines.insert(
            1,
            "The obsolete 'rdkit-pypi' package is installed and often shadows newer 'rdkit' wheels.",
        )
    return "\n".join(lines)


def require_supported_rdkit() -> None:
    """Raise ``RuntimeError`` when the imported RDKit is older than ``MIN_RDKIT_VERSION``."""
    version_tuple = rdkit_version_tuple()
    if version_tuple < MIN_RDKIT_VERSION:
        version = ".".join(str(part) for part in version_tuple)
        raise RuntimeError(unsupported_rdkit_message(version))


def configure_rdkit_for_desktop_app() -> None:
    """Idempotent: require a supported RDKit and reduce console spam when molmanager loads."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    require_supported_rdkit()
    _CONFIGURED = True
    try:
        from rdkit import RDLogger

        RDLogger.DisableLog("rdApp.*")
    except Exception:
        logger.debug("RDKit RDLogger tweak skipped", exc_info=True)
