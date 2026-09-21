# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.


"""Mol* Viewer page assembly for the protein canvas."""

from __future__ import annotations

from pathlib import Path

from .protein_molstar_theme import molstar_theme_css, molstar_theme_tokens

MOLSTAR_VERSION = "5.11.0"
MOLSTAR_CDN_JS = f"https://cdn.jsdelivr.net/npm/molstar@{MOLSTAR_VERSION}/build/viewer/molstar.js"
MOLSTAR_CDN_CSS = (
    f"https://cdn.jsdelivr.net/npm/molstar@{MOLSTAR_VERSION}/build/viewer/molstar.css"
)

_STATIC = Path(__file__).resolve().parent / "static"
_MOLSTAR_JS = _STATIC / "molstar.js"
_MOLSTAR_CSS = _STATIC / "molstar.css"
_BRIDGE_JS = Path(__file__).with_name("protein_molstar.js")


def bundled_molstar_available() -> bool:
    """True when the vendored Mol* Viewer JS and CSS are on disk."""
    return _MOLSTAR_JS.is_file() and _MOLSTAR_CSS.is_file()


def molstar_static_js() -> Path:
    return _MOLSTAR_JS


def molstar_static_css() -> Path:
    return _MOLSTAR_CSS


def _bridge_script() -> str:
    js = _BRIDGE_JS.read_text(encoding="utf-8")
    return "  <script>\n" + js.rstrip("\n") + "\n  </script>\n"


def assemble_molstar_page(*, script_src: str, css_href: str, theme_css: str | None = None) -> str:
    """Return the Mol* Viewer HTML shell (local files or CDN)."""
    extra = '  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n'
    css = theme_css if theme_css is not None else molstar_theme_css()
    bg = molstar_theme_tokens().get("window", "#f0f0f0")
    return (
        "<!DOCTYPE html>\n<html><head>"
        '<meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f'<link rel="stylesheet" type="text/css" href="{css_href}"/>'
        f'<style id="mctoolkit-theme" data-background="{bg}">'
        f"{css}"
        "</style>"
        f"{extra}"
        f'<script src="{script_src}"></script>'
        "</head><body>"
        '<div id="app"></div>'
        f"{_bridge_script()}"
        "</body></html>"
    )


def build_protein_viewer_html() -> str:
    """Return the protein Mol* page (offline bundle when available)."""
    if bundled_molstar_available():
        return assemble_molstar_page(script_src="molstar.js", css_href="molstar.css")
    return assemble_molstar_page(script_src=MOLSTAR_CDN_JS, css_href=MOLSTAR_CDN_CSS)
