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


"""Map the MCToolkit Fusion palette onto Mol* Viewer chrome."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .theme import CUSTOM_PALETTE_ROLES, default_app_font_pt, load_saved_app_font_pt

_DEFAULT_TOKENS: dict[str, str] = {
    "window": "#f0f0f0",
    "window_text": "#000000",
    "base": "#ffffff",
    "alternate_base": "#e8e8e8",
    "text": "#000000",
    "button": "#f0f0f0",
    "button_text": "#000000",
    "highlight": "#308cc6",
    "highlighted_text": "#ffffff",
    "mid": "#a0a0a0",
    "light": "#ffffff",
    "dark": "#505050",
    "link": "#0000ee",
    "tooltip_base": "#ffffdc",
    "tooltip_text": "#000000",
}


def _hex(color: QColor | str) -> str:
    if isinstance(color, str):
        c = QColor(color)
    else:
        c = QColor(color)
    if not c.isValid():
        return "#000000"
    return str(c.name())


def _css_font_family(name: str) -> str:
    raw = (name or "").strip() or "Segoe UI"
    safe = raw.replace("\\", "").replace('"', "")
    return f'"{safe}", Segoe UI, sans-serif'


def molstar_theme_tokens(palette: QPalette | None = None) -> dict[str, str]:
    """Return CSS/JS theme tokens from *palette* or the live application palette."""
    tokens = dict(_DEFAULT_TOKENS)
    pal = palette
    if pal is None:
        app = QApplication.instance()
        if app is not None:
            pal = app.palette()
    if pal is not None:
        for key, _label, role in CUSTOM_PALETTE_ROLES:
            tokens[key] = _hex(pal.color(role))
    app = QApplication.instance()
    family = "Segoe UI"
    pt = default_app_font_pt()
    if app is not None:
        font = app.font()
        family = str(font.family() or family)
        try:
            reported = int(font.pointSize())
        except (TypeError, ValueError):
            reported = 0
        pt = reported if reported > 0 else load_saved_app_font_pt()
    tokens["font_family"] = family
    tokens["font_pt"] = str(int(pt))
    tokens["font_css"] = _css_font_family(family)
    return tokens


def molstar_theme_css(palette: QPalette | None = None) -> str:
    """Overlay stylesheet that recolors Mol* chrome to match MCToolkit."""
    t = molstar_theme_tokens(palette)
    return _css_from_tokens(t)


def molstar_theme_payload(palette: QPalette | None = None) -> dict[str, Any]:
    """JSON payload for ``mctoolkitApplyTheme`` (CSS + 3D canvas background)."""
    t = molstar_theme_tokens(palette)
    return {"css": _css_from_tokens(t), "background": t["window"]}


def refresh_molstar_views(root: QWidget | None) -> None:
    """Push the live Fusion palette onto Mol* hosts under *root*."""
    from .protein_embed import ProteinEmbedView

    if root is None:
        return
    views: list[ProteinEmbedView] = []
    if isinstance(root, ProteinEmbedView):
        views.append(root)
    views.extend(root.findChildren(ProteinEmbedView))
    seen: set[int] = set()
    for view in views:
        ident = id(view)
        if ident in seen:
            continue
        seen.add(ident)
        view.apply_theme()


def _css_from_tokens(t: dict[str, str]) -> str:
    window = t["window"]
    text = t["window_text"]
    base = t["base"]
    alt = t["alternate_base"]
    mid = t["mid"]
    highlight = t["highlight"]
    hi_text = t["highlighted_text"]
    button = t["button"]
    button_text = t["button_text"]
    link = t["link"]
    font = t["font_css"]
    pt = t["font_pt"]
    return f"""
html,body,#app{{width:100%;height:100%;margin:0;overflow:hidden;background:{window};color:{text};}}
msp-plugin{{width:100%;height:100%;display:block;}}
#mctoolkit-theme{{display:none;}}
.msp-plugin{{
  font-family:{font} !important;
  font-size:{pt}pt !important;
  color:{text} !important;
  background:{window} !important;
}}
.msp-plugin .msp-plugin-content,
.msp-plugin .msp-layout-left,
.msp-plugin .msp-layout-right,
.msp-plugin .msp-layout-top,
.msp-plugin .msp-layout-bottom,
.msp-plugin .msp-viewport,
.msp-plugin .msp-sequence,
.msp-plugin .msp-default-bg,
.msp-plugin .msp-left-panel-controls-buttons,
.msp-plugin .msp-section-header,
.msp-plugin .msp-control-group-header,
.msp-plugin .msp-control-group-header>button,
.msp-plugin .msp-control-group-header div,
.msp-plugin .msp-control-row,
.msp-plugin .msp-control-current,
.msp-plugin .msp-row-text,
.msp-plugin .msp-help-text,
.msp-plugin .msp-log li,
.msp-plugin .msp-simple-help-section,
.msp-plugin .msp-current-header,
.msp-plugin .msp-flex-row,
.msp-plugin .msp-no-webgl,
.msp-plugin .msp-semi-transparent-background{{
  background:{window} !important;
  color:{text} !important;
  border-color:{mid} !important;
}}
.msp-plugin .msp-layout-standard,
.msp-plugin .msp-layout-expanded,
.msp-plugin .msp-layout-left,
.msp-plugin .msp-layout-right,
.msp-plugin .msp-layout-top,
.msp-plugin .msp-layout-bottom{{
  border-color:{mid} !important;
}}
.msp-plugin .msp-form-control,
.msp-plugin .msp-btn,
.msp-plugin .msp-btn-action,
.msp-plugin .msp-control-row select,
.msp-plugin .msp-control-row button,
.msp-plugin .msp-control-row input[type=text],
.msp-plugin .msp-control-row>div,
.msp-plugin .msp-sequence-wrapper-non-empty,
.msp-plugin .msp-canvas,
.msp-plugin select.msp-form-control,
.msp-plugin .msp-text-area-wrapper textarea,
.msp-plugin .msp-control-text-area-wrapper textarea{{
  background:{base} !important;
  color:{text} !important;
  border-color:{mid} !important;
}}
.msp-plugin .msp-btn,
.msp-plugin .msp-control-row button,
.msp-plugin .msp-btn-action{{
  background:{button} !important;
  color:{button_text} !important;
}}
.msp-plugin .msp-form-control:hover,
.msp-plugin .msp-btn:hover,
.msp-plugin .msp-btn-link:hover,
.msp-plugin .msp-btn-icon:hover,
.msp-plugin .msp-btn-icon-small:hover,
.msp-plugin .msp-btn-action:hover,
.msp-plugin .msp-control-row select:hover,
.msp-plugin .msp-control-row button:hover,
.msp-plugin .msp-control-row input[type=text]:hover{{
  color:{highlight} !important;
  background:{alt} !important;
  outline-color:{highlight} !important;
}}
.msp-plugin .msp-control-row>span.msp-control-row-label,
.msp-plugin .msp-control-row>button.msp-control-button-label,
.msp-plugin .msp-25-lower-contrast-text,
.msp-plugin .msp-sequence-missing,
.msp-plugin .msp-log-timestamp,
.msp-plugin .msp-tree-row .msp-btn-tree-label>small,
.msp-plugin .msp-btn-link-toggle-off{{
  color:{mid} !important;
}}
.msp-plugin .msp-sequence-present,
.msp-plugin .msp-plugin-content,
.msp-plugin .msp-svg-text{{
  color:{text} !important;
  fill:{text};
}}
.msp-plugin .msp-sequence-wrapper .msp-sequence-label,
.msp-plugin .msp-sequence-chain-label,
.msp-plugin .msp-sequence-wrapper .msp-sequence-number,
.msp-plugin .msp-highlight-info,
.msp-plugin .msp-highlight-info-hr{{
  color:{highlight} !important;
  background-color:{window} !important;
}}
.msp-plugin a{{color:{link} !important;}}
.msp-plugin .msp-log{{background:{alt} !important;color:{text} !important;}}
.msp-plugin .msp-log .msp-log-entry{{background:{base} !important;}}
.msp-plugin .msp-viewport-top-left-controls .msp-traj-controls,
.msp-plugin .msp-viewport-top-left-controls .msp-state-snapshot-viewport-controls>button,
.msp-plugin .msp-selection-viewport-controls-actions,
.msp-plugin .msp-viewport-controls-panel{{
  background:{base} !important;
  color:{text} !important;
}}
.msp-plugin .msp-highlight-toast-wrapper .msp-highlight-info{{
  background:{window} !important;
  color:{highlight} !important;
}}
.msp-plugin .msp-btn-link-toggle-on,
.msp-plugin .msp-btn-link{{color:{text} !important;}}
.msp-plugin .msp-slider-base-rail{{background-color:{alt} !important;}}
.msp-plugin .msp-slider-base-handle{{background-color:{text} !important;border-color:{mid} !important;}}
.msp-plugin .msp-slider-base-handle:hover{{background-color:{highlight} !important;}}
.msp-plugin ::-webkit-scrollbar-track{{background-color:{window} !important;}}
.msp-plugin ::-webkit-scrollbar-thumb{{background-color:{mid} !important;}}
.msp-plugin .msp-accent-offset{{border-left-color:{highlight} !important;}}
.msp-plugin .msp-left-panel-controls-button-data-dirty{{background:{highlight} !important;}}
.msp-plugin .msp-toast-container .msp-toast-entry{{
  color:{text} !important;
  background:{alt} !important;
  border-color:{mid} !important;
}}
.msp-plugin .msp-toast-container .msp-toast-entry .msp-toast-title{{
  background:{window} !important;
  color:{text} !important;
}}
.msp-plugin .msp-selection-viewport-controls select{{
  background:{base} !important;
  color:{text} !important;
}}
.msp-plugin .msp-control-group-header>button,
.msp-plugin .msp-transform-wrapper>.msp-transform-header>button{{
  background:{window} !important;
  color:{text} !important;
}}
.msp-plugin .msp-btn-commit-on{{color:{highlight} !important;background:{button} !important;}}
.msp-plugin mark,
.msp-plugin .msp-sequence-wrapper .msp-sequence-residue-focused{{
  color:{hi_text} !important;
  background:{highlight} !important;
}}
""".strip()
