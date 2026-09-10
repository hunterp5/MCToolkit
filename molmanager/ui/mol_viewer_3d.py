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

"""Interactive molecular viewers using RDKit + bundled 3Dmol.js (3D conformers or 2D coordinates, offline)."""

from __future__ import annotations

import base64
import colorsys
import json
import logging
import math
import shutil
from pathlib import Path

from PyQt5.QtCore import QEvent, QItemSelectionModel, QTemporaryDir, QTimer, QUrl, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem
from rdkit.Chem import AllChem

from ..confs_codec import conformer_mol_blocks_b64_json
from ..exception_policy import log_swallowed_exception
from .property_columns_panel import PropertyColumnsPanel
from .qt_widget_utils import make_window_minimizable
from .widgets import NumericTableWidgetItem

logger = logging.getLogger(__name__)

# Vendored build (https://3dmol.org — BSD). See molmanager/ui/static/3Dmol-min.js
_BUNDLED_3DMOL = Path(__file__).resolve().parent / "static" / "3Dmol-min.js"

# Stick colors for superposed conformers. Overlay slots use unique entries (no wrap).
_SUPERPOSE_PALETTE = (
    "#c0392b",
    "#2980b9",
    "#27ae60",
    "#8e44ad",
    "#f39c12",
    "#16a085",
    "#d35400",
    "#34495e",
    "#e91e63",
    "#3f51b5",
    "#009688",
    "#cddc39",
    "#795548",
    "#00bcd4",
    "#ff5722",
    "#607d8b",
    "#9c27b0",
    "#2196f3",
    "#4caf50",
    "#ffc107",
    "#673ab7",
    "#03a9f4",
    "#8bc34a",
    "#ff9800",
    "#f44336",
    "#3d5afe",
    "#1de9b6",
    "#c6ff00",
    "#a1887f",
    "#18ffff",
    "#ff6e40",
    "#90a4ae",
)


def _hsv_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(float(h) % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def distinct_superpose_colors(n: int) -> list[str]:
    """Return *n* unique hex colors for one superpose overlay (legend and sticks)."""
    want = max(0, int(n))
    if want == 0:
        return []
    if want <= len(_SUPERPOSE_PALETTE):
        return list(_SUPERPOSE_PALETTE[:want])
    out = list(_SUPERPOSE_PALETTE)
    used = {c.lower() for c in out}
    k = 0
    while len(out) < want and k < want * 80:
        hue = (k * 0.618033988749895) % 1.0
        sat = 0.55 + 0.35 * ((k % 5) / 4.0)
        val = 0.55 + 0.35 * (((k // 3) % 5) / 4.0)
        color = _hsv_hex(hue, sat, val)
        k += 1
        if color.lower() in used:
            continue
        used.add(color.lower())
        out.append(color)
    j = 0
    while len(out) < want:
        color = f"#{(37 * j) % 200 + 40:02x}{(91 * j) % 200 + 40:02x}{(17 * j) % 200 + 40:02x}"
        j += 1
        if color.lower() in used:
            continue
        used.add(color.lower())
        out.append(color)
    return out


def superpose_color_for_conf(conf_idx: int) -> str:
    """Unique overlay color for slot *conf_idx* in a growing unique series."""
    i = max(0, int(conf_idx))
    return distinct_superpose_colors(i + 1)[i]


def conf_legend_entries(conf_indices: list[int]) -> list[dict[str, str]]:
    """Legend rows: 1-based Conf id matching the strain table, plus unique stick color."""
    idxs = [int(idx) for idx in conf_indices]
    colors = distinct_superpose_colors(len(idxs))
    return [{"id": str(idx + 1), "color": colors[i]} for i, idx in enumerate(idxs)]


def bundled_3dmol_available() -> bool:
    """True if the vendored 3Dmol script is present (offline-capable viewer)."""
    try:
        return _BUNDLED_3DMOL.is_file() and _BUNDLED_3DMOL.stat().st_size > 10_000
    except OSError:
        return False


def _js_console_is_benign(msg: str) -> bool:
    """True for Chromium/3Dmol noise that should not hit the user console."""
    low = msg.lower()
    if "violation" in low and "non-passive" in low:
        return True
    if "deprecated" in low or "deprecation" in low:
        return True
    if "shared image" in low or "sharedimage" in low:
        return True
    if "invalid mailbox" in low or "non-existent mailbox" in low:
        return True
    if "gl_invalid_operation" in low or "gles2_cmd_decoder" in low:
        return True
    if "webgl" in low:
        return True
    return False


def _log_webengine_js_console(level, message, line, source) -> None:
    """Route JS console lines to Python logging; keep GPU/3Dmol chatter at DEBUG."""
    msg = (message or "").strip()
    if not msg:
        return
    if _js_console_is_benign(msg):
        logger.debug("3D viewer (benign): %s", msg)
        return
    try:
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
    except Exception:
        logger.debug("3D viewer JS: %s", msg)
        return
    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
        logger.warning("3D viewer JS error: %s (line %s, %s)", msg, line, source)
    elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
        logger.debug("3D viewer JS warning: %s", msg)
    else:
        logger.debug("3D viewer JS: %s", msg)


def _wire_webengine_console_logger(web) -> None:
    """
    Capture Qt WebEngine JavaScript console output without dumping it to stderr.

    Qt's default ``QWebEnginePage.javaScriptConsoleMessage`` prints every JS
    console line via ``qWarning``. A custom page swallows that and logs through
    Python instead. GPU SharedImage spam from Chromium itself is suppressed by
    ``configure_qtwebengine_quiet_logs`` before WebEngine starts.
    """
    try:
        from PyQt5.QtWebEngineWidgets import QWebEnginePage

        cls = getattr(_wire_webengine_console_logger, "_page_cls", None)
        if cls is None:

            class QuietWebEnginePage(QWebEnginePage):
                def javaScriptConsoleMessage(self, level, message, line_number, source_id):
                    _log_webengine_js_console(level, message, line_number, source_id)

            cls = QuietWebEnginePage
            _wire_webengine_console_logger._page_cls = cls
        web.setPage(cls(web))
    except Exception:
        logger.debug("3D viewer: could not attach JS console logger", exc_info=True)


def _reset_structure_menu_html() -> str:
    """Right-click menu to restore the originally fitted camera."""
    return """
<style>
  #chem-reset-menu {
    display: none;
    position: fixed;
    z-index: 60;
    min-width: 168px;
    background: #fff;
    border: 1px solid #c8c8c8;
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0,0,0,.16);
    padding: 4px;
    font: 13px/1.3 system-ui, Segoe UI, sans-serif;
  }
  #chem-reset-menu button {
    display: block;
    width: 100%;
    text-align: left;
    border: 0;
    background: transparent;
    padding: 6px 10px;
    border-radius: 4px;
    cursor: pointer;
    color: #111;
  }
  #chem-reset-menu button:hover { background: #e8eef5; }
</style>
<div id="chem-reset-menu" role="menu">
  <button type="button" id="chem-reset-structure" role="menuitem">Reset Structure</button>
</div>
"""


_RESET_STRUCTURE_JS = r"""
        function captureHomeView(v) {
          v = v || window.molmanagerViewer;
          if (!v || typeof v.getView !== "function") return;
          try {
            var home = v.getView();
            if (home && home.length) window.molmanagerHomeView = home.slice();
          } catch (eH) {}
        }
        function applyHomeView(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          var home = window.molmanagerHomeView;
          if (home && home.length && typeof v.setView === "function") {
            try { v.setView(home); v.render(); return; } catch (e1) {}
          }
          try { v.zoomTo(); } catch (e2) {}
          try { v.zoom(0.88); } catch (e3) {}
          v.render();
        }
        function fitAndCapture(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          try { v.zoomTo(); } catch (e1) {}
          try { v.zoom(0.88); } catch (e2) {}
          v.render();
          captureHomeView(v);
        }
        function hideResetMenu() {
          var el = document.getElementById("chem-reset-menu");
          if (el) el.style.display = "none";
        }
        function showResetMenu(clientX, clientY) {
          var el = document.getElementById("chem-reset-menu");
          if (!el) return;
          el.style.display = "block";
          var w = el.offsetWidth || 168;
          var h = el.offsetHeight || 36;
          var x = Math.max(4, Math.min(clientX, window.innerWidth - w - 4));
          var y = Math.max(4, Math.min(clientY, window.innerHeight - h - 4));
          el.style.left = x + "px";
          el.style.top = y + "px";
        }
        function installResetStructureMenu() {
          var host = document.getElementById("v") || document.body;
          var downX = 0, downY = 0;
          host.addEventListener("mousedown", function (e) {
            if (e.button === 2) { downX = e.clientX; downY = e.clientY; }
          });
          host.addEventListener("contextmenu", function (e) {
            e.preventDefault();
            if (Math.abs(e.clientX - downX) > 5 || Math.abs(e.clientY - downY) > 5) return;
            showResetMenu(e.clientX, e.clientY);
          });
          var btn = document.getElementById("chem-reset-structure");
          if (btn) {
            btn.addEventListener("click", function (e) {
              e.preventDefault();
              e.stopPropagation();
              hideResetMenu();
              applyHomeView();
            });
          }
          document.addEventListener("click", function (e) {
            var el = document.getElementById("chem-reset-menu");
            if (!el || el.style.display === "none") return;
            if (el.contains(e.target)) return;
            hideResetMenu();
          });
          document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") hideResetMenu();
          });
          window.molmanagerResetStructure = function () { hideResetMenu(); applyHomeView(); };
        }
"""


def _atom_info_panel_html() -> str:
    """Fixed panel for hover preview and click-selected atom details (3Dmol click/hover callbacks)."""
    return """
<div id="chem-atom-panel" style="position:fixed;top:8px;left:8px;z-index:21;max-width:min(340px,calc(100vw - 16px));font:12px/1.4 system-ui,Segoe UI,sans-serif;background:rgba(255,255,255,0.95);border:1px solid #c8c8c8;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12);padding:8px 10px;pointer-events:none;">
  <div style="font-weight:600;margin-bottom:4px;">Atom</div>
  <div id="chem-atom-hover" style="font-size:11px;color:#555;min-height:1.2em;"></div>
  <div id="chem-atom-detail" style="margin-top:6px;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;font-size:11px;color:#111;"></div>
</div>
"""


def _viewer_init_script_fragment(mol_b64: str, *, flat: bool) -> str:
    """JavaScript to create a 3Dmol viewer (no atom-info panel / mouse-help overlay)."""
    flat_js = "true" if flat else "false"
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        const data = atob("__MOLB64__");
        const flat = __FLAT__;
        const opts = flat ? { backgroundColor: "white", orthographic: true } : { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        __RESET_JS__
        installResetStructureMenu();
        viewer.addModel(data, "mol");
        var stickR = flat ? 0.1 : 0.12;
        var sph = flat ? 0.18 : 0.22;
        viewer.setStyle({}, { stick: { radius: stickR }, sphere: { scale: sph } });
        fitAndCapture(viewer);
        window.molmanagerRefit = function (opts) {
          if (!window.molmanagerViewer) return;
          if (opts && opts.zoom) fitAndCapture(window.molmanagerViewer);
          else {
            try { window.molmanagerViewer.resize(); } catch (e0) {}
            window.molmanagerViewer.render();
          }
        };
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return (
        tmpl.replace("__MOLB64__", mol_b64)
        .replace("__FLAT__", flat_js)
        .replace("__RESET_JS__", _RESET_STRUCTURE_JS)
    )


def _viewer_embed_init_script_fragment(mol_b64: str = "") -> str:
    """Minimal 3Dmol init for sketcher side panel: no atom pick UI; live ``molmanagerSetMolB64``."""
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        __RESET_JS__
        const opts = { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        installResetStructureMenu();
        window.molmanagerRefit = function () { fitAndCapture(window.molmanagerViewer); };
        window.molmanagerSetMolB64 = function (b64) {
          if (!window.molmanagerViewer) return;
          var v = window.molmanagerViewer;
          v.clear();
          if (b64) {
            v.addModel(atob(b64), "mol");
            v.setStyle({}, { stick: { radius: 0.12 }, sphere: { scale: 0.22 } });
            fitAndCapture(v);
          } else {
            v.render();
          }
        };
        window.molmanagerSetMolB64("__MOLB64__");
        window.addEventListener("resize", function () {
          if (window.molmanagerRefit) window.molmanagerRefit();
        });
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return tmpl.replace("__MOLB64__", mol_b64 or "").replace("__RESET_JS__", _RESET_STRUCTURE_JS)


def _assemble_viewer_page(
    mol_b64: str,
    *,
    flat: bool,
    script_src: str,
    show_atom_panel: bool = False,
    show_mouse_help: bool = False,
) -> str:
    init = _viewer_init_script_fragment(mol_b64, flat=flat)
    help_html = _viewer_help_overlay_html() if show_mouse_help else ""
    atom_panel = _atom_info_panel_html() if show_atom_panel else ""
    reset_menu = _reset_structure_menu_html()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}}</style>
</head>
<body>
  <div id="v"></div>
{atom_panel}
{reset_menu}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
{help_html}
</body>
</html>"""


def _assemble_embed_viewer_page(mol_b64: str, *, script_src: str) -> str:
    """Sketcher-embedded page: no atom boxes or mouse-controls overlay."""
    init = _viewer_embed_init_script_fragment(mol_b64)
    reset_menu = _reset_structure_menu_html()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#fff;}}</style>
</head>
<body>
  <div id="v"></div>
{reset_menu}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


def _offline_index_html(mol_b64: str, *, flat: bool = False) -> str:
    """Minimal page next to ``3Dmol-min.js`` (same directory)."""
    return _assemble_viewer_page(mol_b64, flat=flat, script_src="3Dmol-min.js")


def _offline_embed_index_html(mol_b64: str = "") -> str:
    return _assemble_embed_viewer_page(mol_b64, script_src="3Dmol-min.js")


def _offline_index_html_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    return _assemble_viewer_page_multiconf(
        blocks_json_b64,
        script_src="3Dmol-min.js",
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )


def _cdn_fallback_html(mol_b64: str, *, flat: bool = False) -> str:
    """Same as offline page but loads 3Dmol from the network (only if the bundle is missing)."""
    return _assemble_viewer_page(
        mol_b64, flat=flat, script_src="https://3dmol.org/build/3Dmol-min.js"
    )


def _cdn_embed_fallback_html(mol_b64: str = "") -> str:
    return _assemble_embed_viewer_page(mol_b64, script_src="https://3dmol.org/build/3Dmol-min.js")


def _cdn_fallback_html_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    return _assemble_viewer_page_multiconf(
        blocks_json_b64,
        script_src="https://3dmol.org/build/3Dmol-min.js",
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )


def _viewer_help_overlay_html() -> str:
    """On-page reference for 3Dmol.js default GLViewer mouse bindings (matches bundled 3Dmol)."""
    return """
<details id="chem3d-help" style="position:fixed;bottom:6px;right:6px;z-index:20;max-width:min(380px,calc(100vw - 12px));font:12px/1.45 system-ui,Segoe UI,sans-serif;background:rgba(255,255,255,0.94);border:1px solid #c8c8c8;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12);padding:0;">
  <summary style="cursor:pointer;list-style:none;padding:8px 12px;font-weight:600;user-select:none;">Mouse controls</summary>
  <div style="padding:0 12px 10px 12px;border-top:1px solid #e0e0e0;">
    <ul style="margin:0;padding-left:1.1em;">
      <li><b>Click</b> an atom — select &amp; show details (top-left)</li>
      <li><b>Click</b> empty background — clear selection</li>
      <li><b>Hover</b> an atom — quick label under “Atom”</li>
      <li><b>Left drag</b> — rotate the model</li>
      <li><b>Scroll wheel</b> — zoom in / out</li>
      <li><b>Ctrl + wheel</b> — zoom (reversed direction)</li>
      <li><b>Shift + left drag</b> — zoom (vertical drag)</li>
      <li><b>Middle drag</b> — pan (translate)</li>
      <li><b>Ctrl + left drag</b> — pan (translate)</li>
      <li><b>Right drag</b> — zoom (vertical drag)</li>
      <li><b>Ctrl + right drag</b> — adjust front/back clipping (slab)</li>
    </ul>
  </div>
</details>
<style>
#chem3d-help summary::-webkit-details-marker { display: none; }
#chem3d-help[open] summary { border-bottom: 1px solid #e0e0e0; }
</style>
"""


def build_3dmol_html(mol_b64: str) -> str:
    """Return a self-contained HTML document (offline bundle when available, else CDN)."""
    return (
        _offline_index_html(mol_b64, flat=False)
        if bundled_3dmol_available()
        else _cdn_fallback_html(mol_b64, flat=False)
    )


# Ideal pentafluorosulfanyl (–SF5) distances (Å). UFF has no S_6 type and can
# stretch S–F to ~4 Å; ETKDG alone also yields poor octahedral angles.
_SF5_S_F_ANGSTROM = 1.56
_SF5_S_C_ANGSTROM = 1.79


def _has_hypervalent_sulfur(mol: Chem.Mol) -> bool:
    """True when any sulfur has six heavy-atom neighbors (SF5 / SF6)."""
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 16:
            continue
        if sum(1 for nb in atom.GetNeighbors() if nb.GetAtomicNum() > 1) >= 6:
            return True
    return False


def _force_field_safe_for_3d(mol: Chem.Mol) -> bool:
    """
    False when MMFF/UFF are known to corrupt geometry.

    UFF reports success for ``S_6+6`` (SF5) while destroying bond lengths; skip it.
    """
    return not _has_hypervalent_sulfur(mol)


def _regularize_sf5_centers(mol: Chem.Mol) -> int:
    """
    Snap each –SF5 sulfur to octahedral geometry (organic + F axial, 4 F equatorial).

    Returns the number of SF5 centers adjusted. Safe no-op when no conformer / no SF5.
    """
    if mol is None or mol.GetNumConformers() == 0:
        return 0
    try:
        import numpy as np
        from rdkit.Geometry import Point3D
    except Exception:
        return 0

    conf = mol.GetConformer()
    n_fixed = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 16:
            continue
        nbrs = list(atom.GetNeighbors())
        if len(nbrs) != 6:
            continue
        f_idxs = [nb.GetIdx() for nb in nbrs if nb.GetAtomicNum() == 9]
        other_idxs = [nb.GetIdx() for nb in nbrs if nb.GetAtomicNum() != 9]
        if len(f_idxs) != 5 or len(other_idxs) != 1:
            continue
        s_idx = atom.GetIdx()
        o_idx = other_idxs[0]
        s_pos = conf.GetAtomPosition(s_idx)
        o_pos = conf.GetAtomPosition(o_idx)
        axis = np.array([o_pos.x - s_pos.x, o_pos.y - s_pos.y, o_pos.z - s_pos.z], dtype=float)
        norm = float(np.linalg.norm(axis))
        if norm < 1e-6:
            axis = np.array([0.0, 0.0, 1.0])
        else:
            axis = axis / norm
        # Orthonormal equatorial basis.
        helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        eq1 = np.cross(axis, helper)
        eq1 = eq1 / max(float(np.linalg.norm(eq1)), 1e-12)
        eq2 = np.cross(axis, eq1)
        eq2 = eq2 / max(float(np.linalg.norm(eq2)), 1e-12)

        other_el = mol.GetAtomWithIdx(o_idx).GetAtomicNum()
        r_ax = float(_SF5_S_C_ANGSTROM if other_el == 6 else _SF5_S_F_ANGSTROM)
        conf.SetAtomPosition(
            o_idx,
            Point3D(
                float(s_pos.x + axis[0] * r_ax),
                float(s_pos.y + axis[1] * r_ax),
                float(s_pos.z + axis[2] * r_ax),
            ),
        )
        # One F opposite the organic (axial); remaining four equatorial at 90°.
        axial_f, *eq_fs = f_idxs
        conf.SetAtomPosition(
            axial_f,
            Point3D(
                float(s_pos.x - axis[0] * _SF5_S_F_ANGSTROM),
                float(s_pos.y - axis[1] * _SF5_S_F_ANGSTROM),
                float(s_pos.z - axis[2] * _SF5_S_F_ANGSTROM),
            ),
        )
        for i, f_idx in enumerate(eq_fs):
            ang = (math.pi / 2.0) * i
            vec = math.cos(ang) * eq1 + math.sin(ang) * eq2
            conf.SetAtomPosition(
                f_idx,
                Point3D(
                    float(s_pos.x + vec[0] * _SF5_S_F_ANGSTROM),
                    float(s_pos.y + vec[1] * _SF5_S_F_ANGSTROM),
                    float(s_pos.z + vec[2] * _SF5_S_F_ANGSTROM),
                ),
            )
        n_fixed += 1
    return n_fixed


def _seed_crude_3d_coords(mol: Chem.Mol, *, bond_length: float = 1.5) -> bool:
    """
    Place a non-optimized 3D conformer when distance-geometry embed fails.

    Used for –SF5 (and similar) where ETKDG never converges; callers should
    regularize SF5 centers afterward.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return False
    try:
        from collections import deque

        from rdkit.Geometry import Point3D
    except Exception:
        return False
    n = mol.GetNumAtoms()
    conf = Chem.Conformer(n)
    start = 0
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() == 16 and atom.GetDegree() >= 6:
            start = atom.GetIdx()
            break
    conf.SetAtomPosition(start, Point3D(0.0, 0.0, 0.0))
    placed = {start}
    q: deque[int] = deque([start])
    while q:
        u = q.popleft()
        up = conf.GetAtomPosition(u)
        nbrs = [nb.GetIdx() for nb in mol.GetAtomWithIdx(u).GetNeighbors()]
        pending = [v for v in nbrs if v not in placed]
        for i, v in enumerate(pending):
            ang = (2.0 * math.pi * i) / max(len(pending), 1)
            conf.SetAtomPosition(
                v,
                Point3D(
                    float(up.x + bond_length * math.cos(ang)),
                    float(up.y + bond_length * math.sin(ang)),
                    float(up.z + 0.25 * ((i % 3) - 1)),
                ),
            )
            placed.add(v)
            q.append(v)
    for i in range(n):
        if i not in placed:
            conf.SetAtomPosition(i, Point3D(float(i) * bond_length, 0.0, 0.0))
    try:
        mol.RemoveAllConformers()
    except Exception:
        pass
    mol.AddConformer(conf, assignId=True)
    return mol.GetNumConformers() > 0


def prepare_mol_3d(mol: Chem.Mol) -> Chem.Mol | None:
    """
    Return a copy of *mol* with 3D coordinates (ETKDG embed + MMFF/UFF), or ``None`` on failure.

    Sketch-built molecules often carry Kekulé bond orders and a flat 2D conformer.
    Sanitize (aromatize) and clear conformers first so ETKDG uses aromatic ring
    templates — otherwise heterocycles can embed as non-planar.

    Hypervalent sulfur (–SF5) skips MMFF/UFF (UFF invents ``S_6+6`` and wrecks
    geometry) and is regularized to octahedral bond lengths/angles.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    try:
        Chem.SanitizeMol(m)
    except Exception:
        try:
            m.UpdatePropertyCache(strict=False)
            Chem.GetSymmSSSR(m)
            Chem.SetAromaticity(m)
        except Exception:
            try:
                m.UpdatePropertyCache(strict=False)
            except Exception:
                pass
    try:
        m.RemoveAllConformers()
    except Exception:
        pass
    try:
        m = Chem.AddHs(m, addCoords=False)
    except TypeError:
        try:
            m = Chem.AddHs(m)
        except Exception:
            return None
    except Exception:
        return None
    params = None
    for name in ("ETKDGv3", "ETKDGv2", "ETKDG"):
        factory = getattr(AllChem, name, None)
        if factory is None:
            continue
        try:
            params = factory()
            break
        except Exception:
            continue
    if params is None:
        return None
    try:
        # Ignore any leftover coords; embed from distance geometry + ring templates.
        if hasattr(params, "clearConfs"):
            params.clearConfs = True
        if hasattr(params, "useRandomCoords"):
            params.useRandomCoords = True
    except Exception:
        pass
    try:
        cid = AllChem.EmbedMolecule(m, params)
    except Exception:
        cid = -1
    if cid != 0:
        try:
            cid = AllChem.EmbedMolecule(m, randomSeed=0xC0FFEE)
        except Exception:
            cid = -1
    if cid != 0 and _has_hypervalent_sulfur(m):
        # Small SF5 molecules sometimes fail ETKDG entirely; seed + regularize.
        try:
            cid = AllChem.EmbedMolecule(m, useRandomCoords=True, randomSeed=0x5F5)
        except Exception:
            cid = -1
        if cid != 0 and _seed_crude_3d_coords(m):
            cid = 0
    if cid != 0:
        logger.warning("RDKit could not embed a 3D conformer for this structure.")
        return None

    ff_safe = _force_field_safe_for_3d(m)
    if ff_safe:
        mmff_ok = False
        try:
            if AllChem.MMFFHasAllMoleculeParams(m):
                mmff_ok = AllChem.MMFFOptimizeMolecule(m, maxIters=200) == 0
        except Exception:
            mmff_ok = False
        if not mmff_ok:
            try:
                AllChem.UFFOptimizeMolecule(m, maxIters=200)
            except Exception:
                pass
    try:
        _regularize_sf5_centers(m)
    except Exception:
        log_swallowed_exception(logger, "SF5 octahedral regularization failed")
    try:
        m = Chem.RemoveHs(m)
    except Exception:
        pass
    return m


def prepare_mol_2d(mol: Chem.Mol) -> Chem.Mol | None:
    """Return a copy of *mol* with 2D coordinates for a flat depiction, or ``None`` on failure."""
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
    except Exception:
        return None
    try:
        from rdkit.Chem import rdDepictor

        if rdDepictor.Compute2DCoords(m) != 0:
            raise RuntimeError("rdDepictor.Compute2DCoords failed")
    except Exception:
        try:
            if AllChem.Compute2DCoords(m) != 0:
                return None
        except Exception:
            return None
    return m


def _mol_block_b64(mol: Chem.Mol) -> str:
    block = Chem.MolToMolBlock(mol)
    return base64.b64encode(block.encode("utf-8")).decode("ascii")


def _multi_conf_block_count(blocks_json_b64: str | None) -> int:
    """Number of packed conformer mol-blocks in a viewer payload."""
    raw = (blocks_json_b64 or "").strip()
    if not raw:
        return 0
    try:
        blocks = json.loads(base64.b64decode(raw.encode("ascii")))
    except Exception:
        return 0
    return len(blocks) if isinstance(blocks, list) else 0


def _layout_visible_min_width(layout) -> int:
    """Sum size hints of visible widgets in a box layout, including spacing and margins."""
    if layout is None:
        return 0
    try:
        margins = layout.contentsMargins()
        total = int(margins.left() + margins.right())
        spacing = int(layout.spacing())
    except Exception:
        total = 0
        spacing = 0
    n_vis = 0
    try:
        count = int(layout.count())
    except Exception:
        return total
    for i in range(count):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is None or w.isHidden():
            continue
        n_vis += 1
        hint = max(int(w.sizeHint().width()), int(w.minimumSizeHint().width()), 0)
        total += hint
    if n_vis > 1:
        total += spacing * (n_vis - 1)
    return total


def _viewer_init_script_multiconf(
    blocks_json_b64: str,
    *,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    """Multi-conformer 3Dmol page: one-at-a-time vs superpose-all (no on-canvas chrome)."""
    init_sp = "true" if initial_superpose else "false"
    start_idx = max(0, int(initial_conf_index))
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        var initialSuperpose = __INIT_SP__;
        var startIdx = __START_IDX__;
        const blocks = JSON.parse(atob("__BLOCKSJSONB64__"));
        if (!blocks || blocks.length === 0) {
          document.body.innerHTML = "<pre style='padding:12px'>No conformers to display.</pre>";
          return;
        }
        if (blocks.length < 2) initialSuperpose = false;
        startIdx = Math.max(0, Math.min(startIdx, blocks.length - 1));
        var viewer = null;
        var curIdx = startIdx;
        var superposed = false;
        var palette = __PALETTE__;
        __RESET_JS__
        installResetStructureMenu();

        function viewerEl() { return document.getElementById("v"); }
        function viewerReadySize() {
          var el = viewerEl();
          return !!(el && el.clientWidth >= 32 && el.clientHeight >= 32);
        }
        function ensureViewer() {
          if (viewer) return viewer;
          viewer = $3Dmol.createViewer("v", { backgroundColor: "white" });
          window.molmanagerViewer = viewer;
          return viewer;
        }

        function applySingleStyle() {
          viewer.setStyle({}, { stick: { radius: 0.12 }, sphere: { scale: 0.22 } });
        }

        function restyleSuperpose(list, colors) {
          var cols = (colors && colors.length) ? colors : distinctOverlayColors(list.length);
          for (var mi = 0; mi < list.length; mi++) {
            var c = cols[mi] || "#888888";
            viewer.setStyle({ model: mi }, { stick: { radius: 0.09, color: c } });
          }
        }

        function hex2(n) {
          var s = Math.max(0, Math.min(255, Math.round(n))).toString(16);
          return s.length < 2 ? "0" + s : s;
        }
        function hsvHex(h, s, v) {
          var i = Math.floor(h * 6);
          var f = h * 6 - i;
          var p = v * (1 - s);
          var q = v * (1 - f * s);
          var t = v * (1 - (1 - f) * s);
          var r, g, b;
          switch (i % 6) {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            default: r = v; g = p; b = q;
          }
          return "#" + hex2(r * 255) + hex2(g * 255) + hex2(b * 255);
        }
        function distinctOverlayColors(n) {
          n = n | 0;
          if (n <= 0) return [];
          if (n <= palette.length) return palette.slice(0, n);
          var out = palette.slice();
          var used = {};
          for (var u = 0; u < out.length; u++) used[out[u].toLowerCase()] = true;
          var k = 0;
          while (out.length < n && k < n * 80) {
            var h = (k * 0.618033988749895) % 1.0;
            var sat = 0.55 + 0.35 * ((k % 5) / 4.0);
            var val = 0.55 + 0.35 * ((Math.floor(k / 3) % 5) / 4.0);
            var c = hsvHex(h, sat, val);
            k += 1;
            if (used[c.toLowerCase()]) continue;
            used[c.toLowerCase()] = true;
            out.push(c);
          }
          return out;
        }

        function setConfLegend(entries) {
          var el = document.getElementById("chem-conf-legend");
          if (!el) return;
          if (!entries || !entries.length) {
            el.style.display = "none";
            el.innerHTML = "";
            return;
          }
          var parts = ['<div style="font-weight:600;margin-bottom:6px;">Conformers</div>'];
          for (var i = 0; i < entries.length; i++) {
            var id = String(entries[i].id);
            var color = String(entries[i].color || "#888");
            parts.push(
              '<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">'
              + '<span style="flex:0 0 12px;width:12px;height:12px;border-radius:2px;background:'
              + color + ';border:1px solid rgba(0,0,0,.25);"></span>'
              + '<span>Conf ' + id + '</span></div>'
            );
          }
          el.innerHTML = parts.join("");
          el.style.display = "block";
        }

        function allIdxs() {
          var list = [];
          for (var i = 0; i < blocks.length; i++) list.push(i);
          return list;
        }

        function normalizeIdxs(idxs) {
          if (idxs === null || typeof idxs === "undefined") return allIdxs();
          var list = [];
          if (!idxs || !idxs.length) return list;
          for (var k = 0; k < idxs.length; k++) {
            var v = parseInt(idxs[k], 10);
            if (!isFinite(v)) continue;
            v = Math.max(0, Math.min(v, blocks.length - 1));
            if (list.indexOf(v) < 0) list.push(v);
          }
          return list;
        }

        var superposeGen = 0;
        function showSuperpose(idxs, opts) {
          var gen = ++superposeGen;
          var list = normalizeIdxs(idxs);
          var doZoom = !!(opts && opts.zoom);
          if (list.length === 0) {
            superposed = false;
            setConfLegend(null);
            if (viewer) {
              viewer.clear();
              viewer.render();
            }
            return;
          }
          if (list.length === 1) {
            loadConf(list[0]);
            return;
          }
          superposed = true;
          ensureViewer();
          viewer.clear();
          for (var i = 0; i < list.length; i++) {
            if (gen !== superposeGen) return;
            viewer.addModel(atob(blocks[list[i]]), "mol");
          }
          if (gen !== superposeGen) return;
          restyleSuperpose(list, opts && opts.colors);
          if (doZoom) fitAndCapture(viewer);
          else {
            try { viewer.resize(); } catch (e0) {}
            viewer.render();
          }
        }

        function loadConf(i) {
          superposeGen += 1;
          superposed = false;
          setConfLegend(null);
          i = Math.max(0, Math.min(i, blocks.length - 1));
          curIdx = i;
          ensureViewer();
          viewer.clear();
          viewer.addModel(atob(blocks[i]), "mol");
          applySingleStyle();
          fitAndCapture(viewer);
        }

        window.molmanagerRefit = function (opts) {
          if (!viewerReadySize()) return;
          ensureViewer();
          if (opts && opts.zoom) fitAndCapture(viewer);
          else {
            try { viewer.resize(); } catch (e0) {}
            viewer.render();
          }
        };

        function bootView() {
          if (!viewerReadySize()) {
            requestAnimationFrame(bootView);
            return;
          }
          if (initialSuperpose) showSuperpose(null, {zoom: true});
          else loadConf(startIdx);
        }

        window.molmanagerLoadConf = function (i) { loadConf(i); };
        window.molmanagerShowSuperpose = function (idxs, opts) { showSuperpose(idxs, opts); };
        window.molmanagerSetConfLegend = setConfLegend;
        window.molmanagerConfState = function () {
          return { idx: curIdx, superposed: !!superposed, n: blocks.length };
        };
        bootView();
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return (
        tmpl.replace("__BLOCKSJSONB64__", blocks_json_b64)
        .replace("__INIT_SP__", init_sp)
        .replace("__START_IDX__", str(start_idx))
        .replace("__PALETTE__", json.dumps(list(_SUPERPOSE_PALETTE)))
        .replace("__RESET_JS__", _RESET_STRUCTURE_JS)
    )


def _assemble_viewer_page_multiconf(
    blocks_json_b64: str,
    *,
    script_src: str,
    initial_superpose: bool = False,
    initial_conf_index: int = 0,
) -> str:
    init = _viewer_init_script_multiconf(
        blocks_json_b64,
        initial_superpose=initial_superpose,
        initial_conf_index=initial_conf_index,
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}}
    #v{{position:relative;}}
    #chem-conf-legend{{
      display:none;position:absolute;top:8px;right:8px;z-index:20;
      max-width:168px;max-height:calc(100% - 16px);overflow:auto;
      font:12px/1.35 system-ui,Segoe UI,sans-serif;
      background:rgba(255,255,255,0.94);border:1px solid #c8c8c8;border-radius:8px;
      box-shadow:0 2px 8px rgba(0,0,0,.12);padding:8px 10px;
    }}
  </style>
</head>
<body>
  <div id="v"></div>
  <div id="chem-conf-legend"></div>
{_reset_structure_menu_html()}
{init}
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


class Molecule3DEmbedView(QWidget):
    """
    Sketcher side-panel 3Dmol view: no atom-info boxes or mouse-controls overlay.

    Call ``set_molecule`` to refresh after sketch edits (ETKDG embed + MMFF/UFF).
    The WebEngine page is created lazily on first show so QtWebEngine can preload at app start.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_b64: str | None = None
        self._web = None
        self._bootstrapped = False
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(50)
        self._refit_timer.timeout.connect(self.refit_view)
        self._status = QLabel("3D preview", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: palette(mid); padding: 8px;")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
        self.schedule_refit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._web_ready:
            self.schedule_refit()

    def schedule_refit(self) -> None:
        """Debounce resize/zoom so the model fills the frame after layout settles."""
        self._refit_timer.start()

    def refit_view(self) -> None:
        """Resize the WebGL canvas and zoom so the whole structure fits with padding."""
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript("if (window.molmanagerRefit) window.molmanagerRefit();")
        except Exception:
            logger.debug("3D embed refit failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(_offline_embed_index_html(""), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(_cdn_embed_fallback_html(""), QUrl("https://3dmol.org/"))
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Sketcher 3D embed unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D preview unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_b64 is not None:
            b64 = self._pending_b64
            self._pending_b64 = None
            self._run_set_mol_b64(b64)
        if self._web_ready:
            self.schedule_refit()
            QTimer.singleShot(200, self.refit_view)

    def _run_set_mol_b64(self, b64: str) -> None:
        self._ensure_web()
        if self._web is None:
            return
        if not self._web_ready:
            self._pending_b64 = b64
            return
        js = f"if (window.molmanagerSetMolB64) window.molmanagerSetMolB64({json.dumps(b64)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("3D embed set_mol failed", exc_info=True)

    def clear(self) -> None:
        """Clear the displayed model."""
        self._run_set_mol_b64("")

    def set_molecule(self, mol: Chem.Mol | None) -> None:
        """Embed *mol* in 3D and display it, or clear when *mol* is empty/invalid."""
        if mol is None or mol.GetNumAtoms() == 0:
            self.clear()
            return
        m3 = prepare_mol_3d(mol)
        if m3 is None:
            self.clear()
            return
        try:
            self._run_set_mol_b64(_mol_block_b64(m3))
            self.schedule_refit()
            QTimer.singleShot(150, self.refit_view)
        except Exception:
            logger.debug("3D embed encode failed", exc_info=True)
            self.clear()


_STRAIN_TABLE_BASE_HEADERS = (
    "Conf",
    "E",
    "ΔE vs ref",
    "ΔE vs min",
    "Pop. %",
    "RMSD",
)
_STRAIN_FF_COLUMN_ORDER = ("MMFF", "MMFF94s", "UFF")


def _fmt_strain_kcal(value) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""


def populate_strain_energy_table(table: QTableWidget, overlay: dict | None) -> int:
    """Fill a results table with one row per conformer. Returns the row count."""
    table.setSortingEnabled(False)
    table.clearContents()
    table.setRowCount(0)
    if not isinstance(overlay, dict):
        table.setColumnCount(len(_STRAIN_TABLE_BASE_HEADERS))
        table.setHorizontalHeaderLabels(list(_STRAIN_TABLE_BASE_HEADERS))
        return 0
    energies = list(overlay.get("energies") or [])
    n = len(energies)
    deltas = list(overlay.get("deltas") or [])
    deltas_min = list(overlay.get("deltas_min") or [])
    pop_fracs = list(overlay.get("pop_fracs") or [])
    rmsds = list(overlay.get("rmsds") or [])
    primary_ff = str(overlay.get("ff") or "").strip()
    by_ff = overlay.get("energies_by_ff") if isinstance(overlay.get("energies_by_ff"), dict) else {}
    extra_ffs = [
        name
        for name in _STRAIN_FF_COLUMN_ORDER
        if name != primary_ff and isinstance(by_ff.get(name), list) and len(by_ff[name]) == n
    ]
    headers = list(_STRAIN_TABLE_BASE_HEADERS)
    for name in extra_ffs:
        headers.append(f"E ({name})")
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    if n <= 0:
        return 0

    def _at(seq: list, i: int):
        return seq[i] if i < len(seq) else None

    for i in range(n):
        table.insertRow(i)
        conf_item = NumericTableWidgetItem()
        conf_item.setData(Qt.EditRole, float(i + 1))
        conf_item.setText(str(i + 1))
        conf_item.setData(Qt.UserRole, int(i))
        table.setItem(i, 0, conf_item)

        e_item = NumericTableWidgetItem()
        e_item.setData(Qt.EditRole, float(energies[i]))
        e_item.setText(_fmt_strain_kcal(energies[i]))
        table.setItem(i, 1, e_item)

        d_ref = _at(deltas, i)
        d_item = NumericTableWidgetItem()
        if d_ref is None:
            d_item.setText("")
        else:
            d_item.setData(Qt.EditRole, float(d_ref))
            d_item.setText(_fmt_strain_kcal(d_ref))
        table.setItem(i, 2, d_item)

        d_min = _at(deltas_min, i)
        dm_item = NumericTableWidgetItem()
        if d_min is None:
            dm_item.setText("")
        else:
            dm_item.setData(Qt.EditRole, float(d_min))
            dm_item.setText(_fmt_strain_kcal(d_min))
        table.setItem(i, 3, dm_item)

        pop = _at(pop_fracs, i)
        p_item = NumericTableWidgetItem()
        if pop is None:
            p_item.setText("")
        else:
            pct = 100.0 * float(pop)
            p_item.setData(Qt.EditRole, pct)
            p_item.setText(f"{pct:.1f}")
        table.setItem(i, 4, p_item)

        rms = _at(rmsds, i)
        r_item = NumericTableWidgetItem()
        if rms is None:
            r_item.setText("")
        else:
            r_item.setData(Qt.EditRole, float(rms))
            r_item.setText(_fmt_strain_kcal(rms))
        table.setItem(i, 5, r_item)

        for col_i, name in enumerate(extra_ffs, start=6):
            vals = by_ff.get(name) or []
            extra = NumericTableWidgetItem()
            if i < len(vals):
                extra.setData(Qt.EditRole, float(vals[i]))
                extra.setText(_fmt_strain_kcal(vals[i]))
            table.setItem(i, col_i, extra)

    table.setSortingEnabled(True)
    return n


class Molecule3DViewerWidget(QWidget):
    """Interactive 3Dmol structure viewer; float or dock beside the compound table."""

    dockable_in_workspace = True

    def __init__(
        self,
        mol: Chem.Mol,
        parent_app: QWidget | None = None,
        *,
        window_title: str = "View in 3D",
        flat: bool = False,
        multi_conf_blocks_json_b64: str | None = None,
        multi_conf_initial_superpose: bool = False,
        multi_conf_strain_overlay_json_b64: str = "",
        multi_conf_initial_index: int = 0,
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        strain_overlay: dict | None = None,
        source_oid: int | None = None,
    ):
        super().__init__(None)
        self.parent_app = parent_app
        self._window_title = window_title
        self._flat = bool(flat)
        if source_oid is None:
            source_oid = export_parent_oid
        try:
            self._source_oid = int(source_oid) if source_oid is not None else None
        except (TypeError, ValueError):
            self._source_oid = None

        self._multi_conf_blocks_b64 = multi_conf_blocks_json_b64
        self._export_parent_oid = export_parent_oid
        self._export_confs_column = (export_confs_column or "confs").strip() or "confs"
        self._strain_overlay = dict(strain_overlay) if strain_overlay else None
        if self._strain_overlay is None and multi_conf_strain_overlay_json_b64:
            try:
                self._strain_overlay = json.loads(
                    base64.b64decode(multi_conf_strain_overlay_json_b64.encode("ascii"))
                )
            except Exception:
                self._strain_overlay = None
        try:
            self._initial_conf_index = max(0, int(multi_conf_initial_index))
        except (TypeError, ValueError):
            self._initial_conf_index = 0
        self._conf_mode_busy = False
        self._web_refit_size: tuple[int, int] | None = None
        self._web_did_initial_zoom = False

        mol_b64 = _mol_block_b64(mol) if multi_conf_blocks_json_b64 is None else ""
        self._viewer_tmp: QTemporaryDir | None = None
        self._prop_panel: PropertyColumnsPanel | None = None
        self._prop_refresh_wired = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        web = None
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                if multi_conf_blocks_json_b64 is not None:
                    index.write_text(
                        _offline_index_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        encoding="utf-8",
                    )
                else:
                    index.write_text(_offline_index_html(mol_b64, flat=flat), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                if multi_conf_blocks_json_b64 is not None:
                    web.setHtml(
                        _cdn_fallback_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        QUrl("https://3dmol.org/"),
                    )
                else:
                    web.setHtml(_cdn_fallback_html(mol_b64, flat=flat), QUrl("https://3dmol.org/"))
            web.loadFinished.connect(lambda _ok: self._on_standalone_viewer_ready(web))
            web.setMinimumHeight(160)
            web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            root.addWidget(web, 1)
            self._standalone_web = web
        except Exception as e:
            web = None
            self._standalone_web = None
            err = f"{type(e).__name__}: {e}"
            logger.warning("Embedded 3Dmol viewer unavailable: %s", err, exc_info=True)
            msg = (
                "The embedded viewer could not start.\n\n"
                f"{err}\n\n"
                "Typical fixes:\n"
                "• Install PyQtWebEngine with the same major.minor version as PyQt5 (e.g. both 5.15.x).\n"
                "• Start molmanager with `python -m molmanager` so QtWebEngine loads before the GUI initializes.\n\n"
                "Close this window when you are done."
            )
            root.addWidget(QLabel(msg), 1)

        self._strain_table: QTableWidget | None = None
        self._cb_only_selected_confs: QCheckBox | None = None
        if self._strain_overlay:
            self._strain_table = self._build_strain_energy_table()
            root.addWidget(self._strain_table, 0)

        self._conf_nav_host: QWidget | None = None
        self._conf_count = _multi_conf_block_count(multi_conf_blocks_json_b64)
        self._conf_idx = int(getattr(self, "_initial_conf_index", 0) or 0)
        if self._conf_count > 0:
            self._conf_idx = max(0, min(self._conf_idx, self._conf_count - 1))
        self._conf_superposed = bool(multi_conf_initial_superpose) and self._conf_count >= 2

        self._export_host = None
        self._btn_export_table = None
        self._viewer_status = None

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(4)
        self._options_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        # View Conformers is multi-conf; skip table field pickers. Keep them for View 2D/3D.
        if multi_conf_blocks_json_b64 is None:
            self._prop_panel = PropertyColumnsPanel(self._options_host)
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
            options_ly.addWidget(self._prop_panel)
            self._wire_property_column_updates()
            root.addWidget(self._options_host)
        else:
            self._prop_panel = None
            self._options_host.hide()

        footer = QWidget(self)
        footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(6)
        self._add_to_main_btn = QPushButton("Add to Main Window")
        self._add_to_main_btn.setAutoDefault(False)
        self._add_to_main_btn.setDefault(False)
        self._add_to_main_btn.setToolTip(
            "Dock this viewer beside the table in the main window (like a plot pane)."
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = QPushButton("Send to New Window")
        self._send_window_btn.setToolTip("Open this docked viewer in a separate floating window.")
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        self._close_viewer_btn = QPushButton("Close Viewer")
        self._close_viewer_btn.setToolTip(
            "Close this docked viewer and free the panel so another plot or viewer can be docked."
        )
        self._close_viewer_btn.clicked.connect(self._close_docked_viewer)
        foot.addWidget(self._close_viewer_btn)
        if multi_conf_blocks_json_b64 is not None:
            self._add_conf_nav_controls(foot)
            self._btn_export_table = QPushButton("Export to Table")
            self._btn_export_table.setAutoDefault(False)
            self._btn_export_table.setDefault(False)
            self._btn_export_table.setToolTip(
                "Add the current conformer (or all when superposed) to the main table. "
                "Writes 2D Structure, optional E / ΔE / RMSD, and packed 3D into confs when present."
            )
            self._btn_export_table.clicked.connect(self._on_export_to_table)
            if web is None:
                self._btn_export_table.setEnabled(False)
            foot.addWidget(self._btn_export_table)
            self._conf_nav_host = footer
            self._export_host = footer
        foot.addStretch(1)
        if multi_conf_blocks_json_b64 is not None:
            self._viewer_status = QLabel("")
            self._viewer_status.setStyleSheet("color: #333;")
            self._viewer_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            foot.addWidget(self._viewer_status)
        self._apply_footer_size_constraints(foot)
        root.addWidget(footer)
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _wire_property_column_updates(self) -> None:
        """Refresh property values when table cells/headers change."""
        if self._prop_refresh_wired:
            return
        app = self.parent_app
        model = getattr(app, "_table_model", None) if app is not None else None
        if model is None:
            return
        self._prop_refresh_wired = True
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(80)

        def _refresh() -> None:
            panel = self._prop_panel
            if panel is None:
                return
            panel.refresh_columns()
            panel.update_values()

        timer.timeout.connect(_refresh)

        def _schedule(*_args) -> None:
            timer.start()

        model.dataChanged.connect(_schedule)
        model.rowsInserted.connect(_schedule)
        model.rowsRemoved.connect(_schedule)
        model.modelReset.connect(_schedule)
        model.layoutChanged.connect(_schedule)
        model.columnsInserted.connect(_schedule)
        model.columnsRemoved.connect(_schedule)
        try:
            model.headerDataChanged.connect(_schedule)
        except Exception:
            pass

    def _build_strain_energy_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_STRAIN_TABLE_BASE_HEADERS), self)
        table.setObjectName("StrainEnergyTable")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setSortingEnabled(True)
        table.setToolTip(
            "One row per conformer. Click a row to show that pose in 3D. "
            "Ctrl+click or Shift+click to select several. With Selected Conformers checked, "
            "the overlay follows the selection. Click a column header to sort."
        )
        table.setMinimumHeight(140)
        table.setMaximumHeight(240)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        populate_strain_energy_table(table, self._strain_overlay)
        start = int(getattr(self, "_initial_conf_index", 0) or 0)
        table.blockSignals(True)
        try:
            self._select_strain_table_conf(table, start)
        finally:
            table.blockSignals(False)
        table.itemSelectionChanged.connect(self._on_strain_table_selection_changed)
        return table

    def _select_strain_table_conf(self, table: QTableWidget, conf_idx: int) -> None:
        want = int(conf_idx)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) == want:
                    table.selectRow(row)
                    table.scrollToItem(item)
                    return
            except (TypeError, ValueError):
                continue

    def _highlight_current_conf_in_table(self, table: QTableWidget, conf_idx: int) -> None:
        """Move the current row marker without clearing a multi-row selection."""
        want = int(conf_idx)
        model = table.model()
        sm = table.selectionModel()
        if model is None or sm is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) != want:
                    continue
            except (TypeError, ValueError):
                continue
            index = model.index(row, 0)
            sm.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            table.scrollTo(index)
            return

    def _only_selected_in_3d(self) -> bool:
        cb = getattr(self, "_cb_only_selected_confs", None)
        return bool(cb is not None and cb.isChecked())

    def _selected_conf_indices(self) -> list[int]:
        table = self._strain_table
        if table is None:
            return []
        sm = table.selectionModel()
        if sm is None:
            return []
        out: list[int] = []
        for idx in sm.selectedRows():
            item = table.item(idx.row(), 0)
            if item is None:
                continue
            try:
                out.append(int(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        return sorted(set(out))

    def _visible_conf_indices(self) -> list[int]:
        n = int(self._conf_count)
        if n <= 0:
            return []
        if not self._only_selected_in_3d():
            return list(range(n))
        selected = [i for i in self._selected_conf_indices() if 0 <= i < n]
        return selected

    def _current_table_conf_index(self) -> int | None:
        table = self._strain_table
        if table is None:
            return None
        sm = table.selectionModel()
        if sm is None:
            return None
        cur = sm.currentIndex()
        if cur.isValid():
            item = table.item(cur.row(), 0)
            if item is not None:
                try:
                    return int(item.data(Qt.UserRole))
                except (TypeError, ValueError):
                    pass
        selected = self._selected_conf_indices()
        return selected[0] if selected else None

    def _on_strain_table_selection_changed(self) -> None:
        self._sync_superpose_enabled()
        if self._only_selected_in_3d():
            self._refresh_3d_from_scope()
            return
        self._sync_conf_legend()
        if self._conf_superposed:
            return
        idx = self._current_table_conf_index()
        if idx is not None:
            self._show_conformer(idx, preserve_selection=True)

    def _on_only_selected_confs_toggled(self, _checked: bool = False) -> None:
        self._sync_superpose_enabled()
        self._refresh_3d_from_scope()

    def _sync_superpose_enabled(self) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        n_vis = len(self._visible_conf_indices())
        can_super = n_vis >= 2
        cb.setEnabled(can_super)
        if can_super:
            cb.setToolTip("Overlay conformers in the 3D view.")
        else:
            cb.setToolTip("Need at least two visible conformers to superpose.")
            if cb.isChecked():
                self._set_superpose_checked(False)
                self._conf_superposed = False

    def _wants_selected_superpose(self, vis: list[int] | None = None) -> bool:
        idxs = self._visible_conf_indices() if vis is None else vis
        return self._only_selected_in_3d() and len(idxs) >= 2

    def _conf_legend_payload(self) -> list[dict[str, str]] | None:
        """Legend entries when Selected Conformers is on and two-plus poses are overlaid."""
        if not self._only_selected_in_3d() or not self._conf_superposed:
            return None
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            return None
        return conf_legend_entries(vis)

    def _sync_conf_legend(self) -> None:
        payload = self._conf_legend_payload()
        arg = "null" if not payload else json.dumps(payload)
        self._run_viewer_js(f"if (window.molmanagerSetConfLegend) molmanagerSetConfLegend({arg});")

    def _refresh_3d_from_scope(self) -> None:
        vis = self._visible_conf_indices()
        if self._wants_selected_superpose(vis) or (self._conf_superposed and len(vis) >= 2):
            self._show_superpose()
            return
        if not vis:
            self._conf_superposed = False
            self._set_superpose_checked(False)
            self._run_viewer_js("if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);")
            self._sync_conf_legend()
            return
        if self._conf_idx not in vis:
            self._conf_idx = vis[0]
        self._show_conformer(self._conf_idx, preserve_selection=True)

    def _add_conf_nav_controls(self, row: QHBoxLayout) -> None:
        self._btn_conf_first = QPushButton("<<")
        self._btn_conf_first.setToolTip("First conformer (Home)")
        self._btn_conf_back = QPushButton("←")
        self._btn_conf_back.setToolTip("Previous conformer (←)")
        self._btn_conf_fwd = QPushButton("→")
        self._btn_conf_fwd.setToolTip("Next conformer (→)")
        self._btn_conf_last = QPushButton(">>")
        self._btn_conf_last.setToolTip("Last conformer (End)")
        for btn in (
            self._btn_conf_first,
            self._btn_conf_back,
            self._btn_conf_fwd,
            self._btn_conf_last,
        ):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            row.addWidget(btn)

        self._cb_superpose = QCheckBox("Superpose")
        self._cb_superpose.setToolTip("Overlay conformers in the 3D view.")
        if self._conf_count < 2:
            self._cb_superpose.setEnabled(False)
            self._cb_superpose.setToolTip("Need at least two conformers to superpose.")
        self._cb_superpose.setChecked(
            bool(self._conf_superposed) and self._cb_superpose.isEnabled()
        )
        row.addWidget(self._cb_superpose)

        if self._strain_table is not None:
            self._cb_only_selected_confs = QCheckBox("Selected Conformers")
            self._cb_only_selected_confs.setToolTip(
                "When checked, the 3D view follows the table selection. "
                "Two or more selected rows are superposed, with a color legend on the right."
            )
            self._cb_only_selected_confs.toggled.connect(self._on_only_selected_confs_toggled)
            row.addWidget(self._cb_only_selected_confs)

        self._btn_conf_first.clicked.connect(self._go_first_conf)
        self._btn_conf_back.clicked.connect(lambda: self._step_conf(-1))
        self._btn_conf_fwd.clicked.connect(lambda: self._step_conf(1))
        self._btn_conf_last.clicked.connect(self._go_last_conf)
        self._cb_superpose.toggled.connect(self._on_conf_view_mode_toggled)

        for key, slot in (
            (Qt.Key_Home, self._go_first_conf),
            (Qt.Key_Left, lambda: self._step_conf(-1)),
            (Qt.Key_Right, lambda: self._step_conf(1)),
            (Qt.Key_End, self._go_last_conf),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _on_conf_view_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_conf_mode_busy", False):
            return
        self._conf_mode_busy = True
        try:
            if bool(checked):
                self._show_superpose()
            else:
                self._show_conformer(self._conf_idx, preserve_selection=True)
        finally:
            self._conf_mode_busy = False

    def _go_first_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[0], preserve_selection=True)

    def _go_last_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[-1], preserve_selection=True)

    def _step_conf(self, delta: int) -> None:
        vis = self._visible_conf_indices()
        if not vis:
            return
        try:
            pos = vis.index(self._conf_idx)
        except ValueError:
            pos = 0 if int(delta) >= 0 else len(vis) - 1
        else:
            pos = (pos + int(delta)) % len(vis)
        self._show_conformer(vis[pos], preserve_selection=True)

    def _run_viewer_js(self, script: str) -> None:
        web = getattr(self, "_standalone_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(script)
        except Exception:
            logger.debug("viewer JS failed", exc_info=True)

    def _show_superpose(self) -> None:
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            if vis:
                self._show_conformer(vis[0], preserve_selection=True)
            else:
                self._conf_superposed = False
                self._set_superpose_checked(False)
                self._run_viewer_js(
                    "if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);"
                )
                self._sync_conf_legend()
            return
        was_superposed = bool(self._conf_superposed)
        self._conf_superposed = True
        self._set_superpose_checked(True)
        payload = json.dumps(vis) if self._only_selected_in_3d() else "null"
        zoom_js = "false" if was_superposed else "true"
        colors_js = json.dumps(distinct_superpose_colors(len(vis)))
        self._run_viewer_js(
            "if (window.molmanagerShowSuperpose) "
            f"molmanagerShowSuperpose({payload}, {{zoom: {zoom_js}, colors: {colors_js}}});"
        )
        self._sync_conf_legend()

    def _show_conformer(self, conf_idx: int, *, preserve_selection: bool = True) -> None:
        n = int(self._conf_count)
        if n <= 0:
            return
        vis = self._visible_conf_indices()
        idx = max(0, min(int(conf_idx), n - 1))
        if vis and idx not in vis:
            idx = vis[0]
        self._conf_idx = idx
        self._conf_superposed = False
        self._set_superpose_checked(False)
        table = self._strain_table
        if table is not None:
            table.blockSignals(True)
            try:
                if preserve_selection:
                    self._highlight_current_conf_in_table(table, idx)
                else:
                    self._select_strain_table_conf(table, idx)
            finally:
                table.blockSignals(False)
        self._run_viewer_js(f"if (window.molmanagerLoadConf) molmanagerLoadConf({idx});")
        self._sync_conf_legend()

    def _set_superpose_checked(self, superpose: bool) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        cb.blockSignals(True)
        try:
            cb.setChecked(bool(superpose) and cb.isEnabled())
        finally:
            cb.blockSignals(False)

    def rebind_parent_app(self, parent_app: QWidget | None) -> None:
        """Update the host app after dock/undock and refresh property columns."""
        self.parent_app = parent_app
        if self._prop_panel is not None:
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
        self._wire_property_column_updates()

    def embedded_minimum_width(self) -> int:
        host = getattr(self, "_conf_nav_host", None)
        if host is None:
            return 420
        row_w = _layout_visible_min_width(host.layout())
        return max(1200, row_w + 32)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 1280)

    def _apply_footer_size_constraints(self, foot: QHBoxLayout) -> None:
        status = getattr(self, "_viewer_status", None)
        for i in range(foot.count()):
            item = foot.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None or w is status:
                continue
            w.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        foot.setSizeConstraint(QLayout.SetMinimumSize)

    def create_floating_dialog(self, parent_app) -> "Molecule3DViewerDialog":
        """Re-open this viewer in a floating window after undocking from the main table."""
        return Molecule3DViewerDialog(
            None,
            parent_app,
            window_title=self._window_title,
            viewer_widget=self,
        )

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not dock(self):
            return
        if isinstance(dlg, Molecule3DViewerDialog):
            dlg._viewer_widget = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_viewer(self) -> None:
        if self.parent_app is not None:
            close_fn = getattr(self.parent_app, "close_docked_plot", None)
            if callable(close_fn):
                close_fn(self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return getattr(app, "_docked_plot_widget", None) is self

    def _sync_footer_chrome(self) -> None:
        """Floating: Add to Main. Docked: Send/Close. Conformer arrows stay on this row."""
        floating = isinstance(self.window(), Molecule3DViewerDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_viewer_btn.setVisible(docked)
        if not docked:
            self.setMinimumWidth(self.embedded_minimum_width())

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            self._sync_footer_chrome()
        return super().event(event)

    def _host_app(self) -> QWidget | None:
        if self.parent_app is not None:
            return self.parent_app
        parent = self.parent()
        return parent if parent is not None else None

    def _set_viewer_status(self, message: str) -> None:
        msg = (message or "").strip()
        status = getattr(self, "_viewer_status", None)
        if status is not None:
            status.setText(msg)
        app = self._host_app()
        plabel = getattr(app, "status_label", None) if app is not None else None
        if plabel is not None and msg:
            try:
                plabel.setText(msg)
            except Exception:
                pass

    def _on_export_to_table(self) -> None:
        if not self._multi_conf_blocks_b64:
            return
        web = getattr(self, "_standalone_web", None)
        if web is None or self._btn_export_table is None:
            self._set_viewer_status("Export failed: 3D viewer is not available.")
            return
        self._btn_export_table.setEnabled(False)
        self._set_viewer_status("Exporting to table…")

        def _finish(state) -> None:
            try:
                self._export_conformers_to_table(state)
            finally:
                try:
                    self._btn_export_table.setEnabled(True)
                except Exception:
                    pass

        try:
            web.page().runJavaScript(
                "window.molmanagerConfState ? molmanagerConfState() : null",
                _finish,
            )
        except Exception:
            self._btn_export_table.setEnabled(True)
            self._set_viewer_status("Export failed: could not read the current conformer index.")

    def _export_conformers_to_table(self, state) -> None:
        app = self._host_app()
        export_fn = (
            getattr(app, "export_conformer_viewer_to_table", None) if app is not None else None
        )
        if not callable(export_fn):
            self._set_viewer_status(
                "Export failed: open the viewer from the main MolManager window."
            )
            return
        idx = 0
        superposed = False
        n = 0
        if isinstance(state, dict):
            try:
                idx = int(state.get("idx", 0))
            except Exception:
                idx = 0
            superposed = bool(state.get("superposed"))
            try:
                n = int(state.get("n", 0))
            except Exception:
                n = 0
        if superposed or n <= 1:
            if self._only_selected_in_3d():
                selected = self._selected_conf_indices()
                indices = selected if selected else None
            else:
                indices = None
        else:
            indices = [max(0, idx)]
        try:
            n_added = int(
                export_fn(
                    blocks_json_b64=self._multi_conf_blocks_b64,
                    conf_indices=indices,
                    strain_overlay=self._strain_overlay,
                    parent_oid=self._export_parent_oid,
                    confs_column=self._export_confs_column,
                )
            )
        except Exception as exc:
            logger.exception("Export to table failed")
            self._set_viewer_status(f"Export failed: {exc}")
            return
        if n_added <= 0:
            self._set_viewer_status("No conformers were exported.")
            return
        self._set_viewer_status(f"Added {n_added} row(s) to the table.")

    def _on_standalone_viewer_ready(self, web) -> None:
        if self._multi_conf_blocks_b64 and (self._only_selected_in_3d() or self._conf_superposed):
            self._refresh_3d_from_scope()
        else:
            self._sync_conf_legend()
        self._refit_standalone_viewer(web, zoom=True)
        QTimer.singleShot(200, lambda w=web: self._refit_standalone_viewer(w, zoom=True))

    def _refit_standalone_viewer(self, web, *, zoom: bool = False) -> None:
        """Resize the WebGL canvas; zoom only on first load, not on every Qt resize."""
        if web is None:
            return
        js = (
            "if (window.molmanagerRefit) { molmanagerRefit({zoom: "
            + ("true" if zoom else "false")
            + "}); }"
        )
        try:
            web.page().runJavaScript(js)
        except Exception:
            pass
        if zoom and int(web.width()) >= 80 and int(web.height()) >= 80:
            self._web_did_initial_zoom = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        web = getattr(self, "_standalone_web", None)
        if web is None:
            return
        size = (int(web.width()), int(web.height()))
        if size == getattr(self, "_web_refit_size", None):
            return
        self._web_refit_size = size
        QTimer.singleShot(80, lambda w=web, s=size: self._refit_after_resize(w, s))

    def _refit_after_resize(self, web, size: tuple[int, int]) -> None:
        if getattr(self, "_web_refit_size", None) != size:
            return
        w, h = size
        first = not getattr(self, "_web_did_initial_zoom", False) and w >= 80 and h >= 80
        if first:
            self._web_did_initial_zoom = True
        self._refit_standalone_viewer(web, zoom=first)


class Molecule3DViewerDialog(QDialog):
    """Floating window hosting a :class:`Molecule3DViewerWidget`."""

    def __init__(
        self,
        mol: Chem.Mol | None,
        parent: QWidget | None = None,
        *,
        window_title: str = "View in 3D",
        flat: bool = False,
        multi_conf_blocks_json_b64: str | None = None,
        multi_conf_initial_superpose: bool = False,
        multi_conf_strain_overlay_json_b64: str = "",
        multi_conf_initial_index: int = 0,
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        strain_overlay: dict | None = None,
        source_oid: int | None = None,
        viewer_widget: Molecule3DViewerWidget | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle(window_title)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False

        if viewer_widget is not None:
            self._viewer_widget = viewer_widget
            self._viewer_widget.setParent(self)
            self._viewer_widget._window_title = window_title
            self._viewer_widget.rebind_parent_app(parent)
        else:
            if mol is None:
                raise ValueError("mol is required when viewer_widget is not provided")
            self._viewer_widget = Molecule3DViewerWidget(
                mol,
                parent,
                window_title=window_title,
                flat=flat,
                multi_conf_blocks_json_b64=multi_conf_blocks_json_b64,
                multi_conf_initial_superpose=multi_conf_initial_superpose,
                multi_conf_strain_overlay_json_b64=multi_conf_strain_overlay_json_b64,
                multi_conf_initial_index=multi_conf_initial_index,
                export_parent_oid=export_parent_oid,
                export_confs_column=export_confs_column,
                strain_overlay=strain_overlay,
                source_oid=source_oid,
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._viewer_widget, 1)
        self._viewer_widget._sync_footer_chrome()
        make_window_minimizable(self)
        min_w = int(self._viewer_widget.embedded_minimum_width())
        self._viewer_widget.setMinimumWidth(min_w)
        self.setMinimumWidth(min_w)
        self.resize(max(min_w, 1280), 800)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if self._force_close:
            self._force_close = False
        event.accept()


def open_molecule_3d_viewer(
    mol: Chem.Mol,
    parent: QWidget | None = None,
    *,
    title: str = "View in 3D",
    source_oid: int | None = None,
) -> None:
    """Show *mol* in 3Dmol: multiple RDKit conformers use a conformer slider; otherwise embed once (ETKDG)."""
    if mol is None or not isinstance(mol, Chem.Mol):
        return
    try:
        nconf = int(mol.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf > 1:
        try:
            m = Chem.Mol(mol)
        except Exception:
            m = mol
        payload = conformer_mol_blocks_b64_json(m)
        try:
            inner = json.loads(base64.b64decode(payload.encode("ascii")))
        except Exception:
            inner = []
        if not inner:
            QMessageBox.warning(
                parent,
                title,
                "This molecule reports multiple conformers but none could be serialized for the 3D viewer.",
            )
            return
        win_title = title if title else "View in 3D"
        if win_title == "View in 3D":
            win_title = "View Conformers"
        win_title = f"{win_title} ({len(inner)} conformers)"
        dlg = Molecule3DViewerDialog(
            m,
            parent,
            window_title=win_title,
            flat=False,
            multi_conf_blocks_json_b64=payload,
            multi_conf_initial_superpose=False,
            source_oid=source_oid,
            export_parent_oid=source_oid,
        )
        dlg.show()
        return

    m3d = prepare_mol_3d(mol)
    if m3d is None:
        QMessageBox.warning(
            parent,
            title,
            "Could not build a 3D conformation for this structure.\n"
            "Try editing the structure or simplifying the molecule.",
        )
        return
    dlg = Molecule3DViewerDialog(m3d, parent, window_title=title, flat=False, source_oid=source_oid)
    dlg.show()


def open_conformation_viewer_from_blocks_payload(
    parent: QWidget | None,
    blocks_json_b64: str,
    *,
    title: str = "View Conformers",
    initial_superpose: bool = False,
    strain_overlay: dict | None = None,
    initial_conf_index: int = 0,
    export_parent_oid: int | None = None,
    export_confs_column: str = "confs",
    source_oid: int | None = None,
) -> None:
    """Open the multi-conformer 3Dmol viewer (one-at-a-time and/or superpose) from packed mol blocks."""
    b = (blocks_json_b64 or "").strip()
    if not b:
        return
    n = 0
    try:
        inner = json.loads(base64.b64decode(b.encode("ascii")))
        if isinstance(inner, list):
            n = len(inner)
    except Exception:
        pass
    if n < 1:
        QMessageBox.warning(
            parent,
            title,
            "No conformers could be read from this cell for the 3D viewer.",
        )
        return
    strain_b64 = ""
    if strain_overlay:
        try:
            strain_b64 = base64.b64encode(
                json.dumps(strain_overlay, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
        except Exception:
            strain_b64 = ""
    dummy = Chem.MolFromSmiles("C")
    win_title = title if title else "View Conformers"
    if n > 1:
        win_title = f"{win_title} ({n} conformers)"
    if source_oid is None:
        source_oid = export_parent_oid
    dlg = Molecule3DViewerDialog(
        dummy,
        parent,
        window_title=win_title,
        flat=False,
        multi_conf_blocks_json_b64=b,
        multi_conf_initial_superpose=initial_superpose,
        multi_conf_strain_overlay_json_b64=strain_b64,
        multi_conf_initial_index=int(initial_conf_index),
        export_parent_oid=export_parent_oid,
        export_confs_column=export_confs_column,
        strain_overlay=strain_overlay,
        source_oid=source_oid,
    )
    dlg.show()


def open_molecule_2d_viewer(
    mol: Chem.Mol,
    parent: QWidget | None = None,
    *,
    title: str = "View in 2D",
    source_oid: int | None = None,
) -> None:
    """Lay out *mol* in 2D and show it in 3Dmol with an orthographic (flat) projection."""
    if mol is None or not isinstance(mol, Chem.Mol):
        return
    m2d = prepare_mol_2d(mol)
    if m2d is None:
        QMessageBox.warning(
            parent,
            title,
            "Could not compute a 2D layout for this structure.",
        )
        return
    dlg = Molecule3DViewerDialog(m2d, parent, window_title=title, flat=True, source_oid=source_oid)
    dlg.show()
