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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Protein structure viewer: 3Dmol.js canvas plus a PyMOL-style chain Manager."""

from __future__ import annotations

import base64
import json
import logging
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from PyQt5.QtCore import QObject, QTemporaryDir, QTimer, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QActionGroup,
    QColorDialog,
    QDialog,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMenuBar,
    QMessageBox,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..structure_components import (
    LoadedStructure,
    PolymerChain,
    StructureComponent,
    cif_viewer_bond_tables,
    component_id_for_atom,
    delete_pdb_residues,
    letter_to_resn,
    load_structure_file,
    parse_polymer_sequences,
    pocket_view_plan,
    polymer_residue_for_atom,
    rewrite_pdb_residue_names,
    scope_structure_component,
)
from .mol_viewer_3d import (
    _BUNDLED_3DMOL,
    _RESET_STRUCTURE_JS,
    _reset_structure_menu_html,
    _wire_webengine_console_logger,
    bundled_3dmol_available,
)
from .protein_sequence import ProteinSequenceDialog
from .qt_widget_utils import make_window_minimizable, qobject_is_deleted

logger = logging.getLogger(__name__)

COMPONENT_STYLE_CHOICES = (
    ("cartoon", "Cartoon"),
    ("surface", "Surface"),
    ("stick", "Sticks"),
    ("ballstick", "Ball and stick"),
    ("sphere", "Spheres"),
    ("line", "Wireframe"),
)

COMPONENT_COLOR_CHOICES = (
    ("default", "Default"),
    ("gray", "Gray"),
    ("green", "Green"),
    ("cyan", "Cyan"),
    ("magenta", "Magenta"),
    ("yellow", "Yellow"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("blue", "Blue"),
)

# cartoon color, 3Dmol carbon colorscheme (hex keeps Jmol heteroatoms)
_RENDER_COLOR_SPEC = {
    "gray": ("#888888", "#888888"),
    "green": ("green", "greenCarbon"),
    "cyan": ("cyan", "cyanCarbon"),
    "magenta": ("magenta", "magentaCarbon"),
    "yellow": ("yellow", "yellowCarbon"),
    "orange": ("orange", "orangeCarbon"),
    "purple": ("purple", "purpleCarbon"),
    "blue": ("blue", "blueCarbon"),
}

STRUCTURE_FILE_FILTER = (
    "Crystallographic files (*.pdb *.ent *.cif *.mmcif *.mcif *.pdbqt *.pqr);;"
    "PDB (*.pdb *.ent);;"
    "mmCIF (*.cif *.mmcif *.mcif);;"
    "PDBQT (*.pdbqt);;"
    "PQR (*.pqr);;"
    "Other 3D (*.gro *.mol2 *.sdf *.xyz);;"
    "All files (*.*)"
)

_ID_ROLE = Qt.UserRole
_KIND_ROLE = Qt.UserRole + 1
_STRUCT_ROLE = Qt.UserRole + 2


@dataclass
class _ComponentView:
    spec: StructureComponent
    visible: bool
    selected: bool
    style: str
    color_scheme: str = "default"


@dataclass
class _LoadedSlot:
    structure_id: str
    name: str
    path: Path
    text: str
    fmt: str
    rows: list[_ComponentView]


def _viewer_protein_init_script() -> str:
    tmpl = r"""  <script>
    function molmanagerInitView() {
      try {
        __RESET_JS__
        function keepViewResize(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var saved = null;
          try { saved = v.getView(); } catch (eV) {}
          try { v.resize(); } catch (eR) {}
          if (saved && saved.length && typeof v.setView === "function") {
            try { v.setView(saved); } catch (eSet) {}
          }
          v.render();
        }
        function selOf(comp) {
          var sel = (comp && comp.selection) ? comp.selection : {};
          if (!comp || (comp.kind !== "ligand" && comp.kind !== "metal")) return sel;
          var parts = [];
          var seen = {};
          function addPart(extra) {
            var s = {};
            for (var k in sel) {
              if (Object.prototype.hasOwnProperty.call(sel, k)) s[k] = sel[k];
            }
            for (var ek in extra) s[ek] = extra[ek];
            var key = JSON.stringify(s);
            if (seen[key]) return;
            seen[key] = true;
            parts.push(s);
          }
          var resi = sel.resi;
          var resis = [];
          if (resi != null && resi !== "") {
            if (Array.isArray(resi)) resis = resi.slice();
            else {
              resis.push(resi);
              if (typeof resi === "number") resis.push(String(resi));
              else {
                var n = parseInt(resi, 10);
                if (!isNaN(n)) resis.push(n);
              }
            }
          }
          if (resis.length) {
            for (var i = 0; i < resis.length; i++) addPart({resi: resis[i]});
          } else {
            addPart({});
          }
          var loose = {chain: sel.chain, resn: sel.resn, hetflag: true};
          if (sel.model != null && sel.model !== "") loose.model = sel.model;
          var looseKey = JSON.stringify(loose);
          if (!seen[looseKey]) {
            seen[looseKey] = true;
            parts.push(loose);
          }
          return parts.length === 1 ? parts[0] : {or: parts};
        }
        function carbonSpec(base, comp) {
          var out = {};
          for (var k in base) {
            if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
          }
          out.hidden = false;
          var scheme = comp && comp.carbonScheme;
          if (!scheme) return out;
          if (String(scheme).charAt(0) === "#") {
            var map = {};
            try {
              var src = ($3Dmol.elementColors && $3Dmol.elementColors.Jmol) || {};
              for (var el in src) {
                if (Object.prototype.hasOwnProperty.call(src, el)) map[el] = src[el];
              }
            } catch (eMap) {}
            map.C = scheme;
            out.colorscheme = {prop: "elem", map: map};
          } else {
            out.colorscheme = scheme;
          }
          return out;
        }
        function applyOneStyle(v, comp) {
          if (!comp) return;
          var sel = selOf(comp);
          try { v.removeSurface && v.removeSurface(sel); } catch (eRs) {}
          if (!comp.visible) {
            v.setStyle(sel, {hidden: true});
            return;
          }
          var color = comp.cartoonColor || comp.color || undefined;
          var style = comp.style || "stick";
          if (style === "cartoon") {
            v.setStyle(sel, {cartoon: {color: color || "spectrum", hidden: false}});
          } else if (style === "surface") {
            var surfColor = color || "lightgray";
            if (surfColor === "spectrum") surfColor = comp.color || "lightgray";
            v.setStyle(sel, {cartoon: {color: surfColor, hidden: false}});
            try {
              v.addSurface($3Dmol.SurfaceType.VDW, {opacity: 0.65, color: surfColor === "spectrum" ? "white" : surfColor}, sel);
            } catch (eSurf) {}
          } else if (style === "stick") {
            v.setStyle(sel, {stick: carbonSpec({radius: 0.15}, comp)});
          } else if (style === "sphere") {
            var scale = (comp.kind === "water") ? 0.35 : (comp.kind === "metal" ? 0.55 : 0.4);
            v.setStyle(sel, {sphere: carbonSpec({scale: scale}, comp)});
          } else if (style === "line") {
            v.setStyle(sel, {line: carbonSpec({linewidth: 1.5}, comp)});
          } else {
            v.setStyle(sel, {
              stick: carbonSpec({radius: 0.18}, comp),
              sphere: carbonSpec({scale: 0.26}, comp)
            });
          }
          if (comp.selected && comp.visible && !(window.molmanagerResidueHighlight || []).length) {
            try {
              if (style === "cartoon" || style === "surface") {
                v.addStyle(sel, {cartoon: {color: "orange"}});
              } else {
                v.addStyle(sel, {stick: {radius: 0.22, color: "orange"}});
              }
            } catch (eSel) {}
          }
        }
        function applyResidueHighlight(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var sels = window.molmanagerResidueHighlight || [];
          if (!sels.length) return;
          var sel = sels.length === 1 ? sels[0] : {or: sels};
          try {
            v.addStyle(sel, {cartoon: {color: "orange"}});
            v.addStyle(sel, {stick: {radius: 0.22, color: "orange"}, sphere: {scale: 0.28}});
          } catch (eHi) {}
        }
        function applyCifBondOrders(v, tables, modelId) {
          if (!v || !tables) return;
          var atoms;
          try { atoms = v.selectedAtoms({}); } catch (eAtoms) { return; }
          if (!atoms || !atoms.length) return;
          if (modelId != null && modelId !== "") {
            atoms = atoms.filter(function (at) {
              var mid = (at.model && typeof at.model.id === "number")
                ? at.model.id
                : (typeof at.model === "number" ? at.model : 0);
              return mid === modelId;
            });
          }
          if (!atoms.length) return;
          function normName(n) {
            return String(n || "").replace(/["']/g, "").trim();
          }
          var groups = {};
          for (var i = 0; i < atoms.length; i++) {
            var at = atoms[i];
            var resn = String(at.resn || "").trim();
            if (!tables[resn]) continue;
            var key = (at.chain || "") + "\t" + (at.resi == null ? "" : String(at.resi))
              + "\t" + (at.icode || "") + "\t" + resn;
            if (!groups[key]) groups[key] = {resn: resn, byName: {}};
            var name = normName(at.atom || at.name || at.label_atom_id);
            if (!name) continue;
            if (!groups[key].byName[name]) groups[key].byName[name] = [];
            groups[key].byName[name].push(at);
          }
          function pick(list) {
            if (!list || !list.length) return null;
            for (var j = 0; j < list.length; j++) {
              var alt = list[j].altLoc || list[j].altloc || "";
              if (!alt || alt === " " || alt === "A") return list[j];
            }
            return list[0];
          }
          function partnerIndex(atom, other) {
            if (!atom.bonds) return -1;
            var want = (typeof other.index === "number") ? other.index : other;
            var found = atom.bonds.indexOf(want);
            if (found >= 0) return found;
            return atom.bonds.indexOf(other);
          }
          function setBond(a, b, order) {
            if (!a || !b || a === b) return;
            if (!a.bonds) a.bonds = [];
            if (!b.bonds) b.bonds = [];
            if (!a.bondOrder) a.bondOrder = [];
            if (!b.bondOrder) b.bondOrder = [];
            var ia = partnerIndex(a, b);
            if (ia >= 0) a.bondOrder[ia] = order;
            else {
              a.bonds.push(typeof b.index === "number" ? b.index : b);
              a.bondOrder.push(order);
            }
            var ib = partnerIndex(b, a);
            if (ib >= 0) b.bondOrder[ib] = order;
            else {
              b.bonds.push(typeof a.index === "number" ? a.index : a);
              b.bondOrder.push(order);
            }
          }
          for (var gk in groups) {
            if (!Object.prototype.hasOwnProperty.call(groups, gk)) continue;
            var g = groups[gk];
            var bonds = tables[g.resn] || [];
            for (var bi = 0; bi < bonds.length; bi++) {
              var pair = bonds[bi];
              if (!pair || pair.length < 3) continue;
              var a1 = pick(g.byName[normName(pair[0])]);
              var a2 = pick(g.byName[normName(pair[1])]);
              var ord = parseInt(pair[2], 10);
              if (!a1 || !a2 || !(ord > 1)) continue;
              setBond(a1, a2, ord);
            }
          }
        }
        function applyAll(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.removeAllSurfaces(); } catch (eS) {}
          try { v.removeAllLabels(); } catch (eL) {}
          try { v.setStyle({}, {}); } catch (eH) {}
          var comps = window.molmanagerComponents || [];
          for (var i = 0; i < comps.length; i++) applyOneStyle(v, comps[i]);
          applyPocketOverlay(v);
          applyResidueHighlight(v);
        }
        function addPocketResidueLabels(v, residueSels) {
          if (!residueSels || !residueSels.length || typeof v.addResLabels !== "function") return;
          var parts = [];
          for (var i = 0; i < residueSels.length; i++) {
            var src = residueSels[i] || {};
            var ca = {};
            for (var k in src) {
              if (Object.prototype.hasOwnProperty.call(src, k)) ca[k] = src[k];
            }
            ca.atom = "CA";
            parts.push(ca);
          }
          var sel = parts.length === 1 ? parts[0] : {or: parts};
          try {
            v.addResLabels(sel, {
              fontSize: 12,
              fontColor: "black",
              showBackground: true,
              backgroundColor: "white",
              backgroundOpacity: 0.88,
              inFront: true
            });
          } catch (eLab) {}
        }
        function removePocketHModel(v) {
          if (window.molmanagerPocketHModel) {
            try { v.removeModel(window.molmanagerPocketHModel); } catch (eRm) {}
            window.molmanagerPocketHModel = null;
          }
        }
        function applyPocketOverlay(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          removePocketHModel(v);
          var p = window.molmanagerPocket;
          if (!p || !p.active) return;
          var resSels = p.residueSels || [];
          var ligSels = p.ligandSels || [];
          var parts = resSels.concat(ligSels);
          if (parts.length) {
            var sel = parts.length === 1 ? parts[0] : {or: parts};
            try {
              v.addStyle(sel, {stick: {radius: 0.18}, sphere: {scale: 0.26}});
            } catch (eBs) {}
            try {
              v.addStyle({and: [sel, {elem: "H"}]}, {hidden: true});
              v.addStyle({and: [sel, {elem: "D"}]}, {hidden: true});
            } catch (eHide) {}
          }
          addPocketResidueLabels(v, resSels);
          if (!p.polarHPdb) return;
          try {
            var mdl = v.addModel(atob(p.polarHPdb), "pdb");
            window.molmanagerPocketHModel = mdl;
            var mid = (mdl && mdl.id != null) ? mdl.id : null;
            if (mid == null) {
              try { mid = v.getModel().id; } catch (eG) {}
            }
            if (mid == null) return;
            v.setStyle({model: mid}, {hidden: true});
            v.setStyle(
              {model: mid, elem: "H"},
              {stick: {radius: 0.08, color: "white"}, sphere: {scale: 0.18, color: "white"}}
            );
          } catch (eHmod) {}
        }
        function bindPicking(v) {
          try {
            v.setClickable({}, true, function (atom) {
              if (!atom) return;
              var payload = JSON.stringify({
                chain: atom.chain || "",
                resn: atom.resn || "",
                resi: atom.resi == null ? "" : String(atom.resi),
                icode: atom.icode || "",
                model: (atom.model && typeof atom.model.id === "number")
                  ? atom.model.id
                  : (typeof atom.model === "number" ? atom.model : 0)
              });
              if (window.proteinBridge && window.proteinBridge.atomPicked) {
                window.proteinBridge.atomPicked(payload);
              }
            });
          } catch (eClick) {}
        }
        function connectBridge() {
          try {
            if (typeof QWebChannel !== "function" || typeof qt === "undefined") return;
            new QWebChannel(qt.webChannelTransport, function (channel) {
              window.proteinBridge = channel.objects.proteinBridge || null;
            });
          } catch (eCh) {}
        }
        const opts = { backgroundColor: "white" };
        const viewer = $3Dmol.createViewer("v", opts);
        window.molmanagerViewer = viewer;
        window.molmanagerComponents = [];
        window.molmanagerFmt = "pdb";
        window.molmanagerResidueHighlight = [];
        window.molmanagerPocket = null;
        window.molmanagerPocketHModel = null;
        installResetStructureMenu();
        connectBridge();
        bindPicking(viewer);
        window.molmanagerResizeKeepView = function () { keepViewResize(window.molmanagerViewer); };
        window.molmanagerSetProteinPayload = function (payload) {
          if (!window.molmanagerViewer || !payload) return;
          var v = window.molmanagerViewer;
          window.molmanagerComponents = payload.components || [];
          window.molmanagerFmt = payload.fmt || "pdb";
          if (payload.residueHighlight) {
            window.molmanagerResidueHighlight = payload.residueHighlight;
          }
          window.molmanagerPocket = payload.pocket || null;
          var refit = !!payload.refit;
          v.clear();
          window.molmanagerPocketHModel = null;
          try { v.removeAllSurfaces(); } catch (eClr) {}
          var models = payload.models;
          if (!models || !models.length) {
            models = payload.data ? [{data: payload.data, fmt: payload.fmt || "pdb"}] : [];
          }
          for (var m = 0; m < models.length; m++) {
            var md = models[m] || {};
            var data = md.data || "";
            var fmt = md.fmt || window.molmanagerFmt || "pdb";
            if (!data) continue;
            try { v.addModel(atob(data), fmt); } catch (eAdd) {
              document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + eAdd + "</pre>";
              return;
            }
            if (md.cifBonds) {
              try { applyCifBondOrders(v, md.cifBonds, m); } catch (eBonds) {}
            }
          }
          applyAll(v);
          bindPicking(v);
          if (refit) {
            fitAndCapture(v);
          } else {
            keepViewResize(v);
          }
        };
        window.molmanagerApplyComponentStates = function (components) {
          if (!window.molmanagerViewer) return;
          if (components) window.molmanagerComponents = components;
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerDeleteComponents = function (ids) {
          if (!window.molmanagerViewer || !ids || !ids.length) return;
          var v = window.molmanagerViewer;
          var model = null;
          try { model = v.getModel(); } catch (eM) {}
          var keep = [];
          var comps = window.molmanagerComponents || [];
          var drop = {};
          for (var d = 0; d < ids.length; d++) drop[ids[d]] = true;
          for (var i = 0; i < comps.length; i++) {
            var comp = comps[i];
            if (drop[comp.id]) {
              try {
                var atoms = v.selectedAtoms(selOf(comp));
                if (atoms && atoms.length) {
                  var mdl = atoms[0].model || model;
                  if (!mdl) {
                    try { mdl = v.getModel(); } catch (eM2) {}
                  }
                  if (mdl && mdl.removeAtoms) mdl.removeAtoms(atoms);
                }
              } catch (eRm) {}
            } else {
              keep.push(comp);
            }
          }
          window.molmanagerComponents = keep;
          applyAll(v);
          keepViewResize(v);
        };
        window.molmanagerSetResidueHighlight = function (sels) {
          window.molmanagerResidueHighlight = sels || [];
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerSetPocket = function (pocket) {
          window.molmanagerPocket = pocket || null;
          if (!window.molmanagerViewer) return;
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerMutateResidues = function (items) {
          var v = window.molmanagerViewer;
          if (!v || !items) return;
          for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var sel = {chain: it.chain, resi: it.resi};
            if (it.icode) sel.icode = it.icode;
            if (it.model != null && it.model !== "") sel.model = it.model;
            try {
              var atoms = v.selectedAtoms(sel);
              for (var a = 0; a < atoms.length; a++) atoms[a].resn = it.resn;
            } catch (eMut) {}
          }
          applyAll(v);
          keepViewResize(v);
        };
        window.molmanagerDeleteResidues = function (sels) {
          var v = window.molmanagerViewer;
          if (!v || !sels || !sels.length) return;
          var model = null;
          try { model = v.getModel(); } catch (eM) {}
          for (var i = 0; i < sels.length; i++) {
            try {
              var atoms = v.selectedAtoms(sels[i]);
              if (atoms && atoms.length) {
                var mdl = atoms[0].model || model;
                if (!mdl) {
                  try { mdl = v.getModel(); } catch (eM2) {}
                }
                if (mdl && mdl.removeAtoms) mdl.removeAtoms(atoms);
              }
            } catch (eRm) {}
          }
          applyAll(v);
          keepViewResize(v);
        };
        window.molmanagerZoomToComponents = function (ids) {
          var v = window.molmanagerViewer;
          if (!v) return;
          var comps = window.molmanagerComponents || [];
          var want = {};
          for (var d = 0; d < (ids || []).length; d++) want[ids[d]] = true;
          var parts = [];
          for (var i = 0; i < comps.length; i++) {
            if (want[comps[i].id]) parts.push(selOf(comps[i]));
          }
          try { v.resize(); } catch (e0) {}
          try {
            if (parts.length === 1) v.zoomTo(parts[0]);
            else if (parts.length > 1) v.zoomTo({or: parts});
            else v.zoomTo();
          } catch (eZ) { try { v.zoomTo(); } catch (eZ2) {} }
          try { v.zoom(0.85); } catch (eZoom) {}
          v.render();
          captureHomeView(v);
        };
        window.molmanagerZoomToSelections = function (sels) {
          var v = window.molmanagerViewer;
          if (!v) return;
          try { v.resize(); } catch (e0) {}
          try {
            if (!sels || !sels.length) v.zoomTo();
            else if (sels.length === 1) v.zoomTo(sels[0]);
            else v.zoomTo({or: sels});
          } catch (eZ) { try { v.zoomTo(); } catch (eZ2) {} }
          try { v.zoom(0.85); } catch (eZoom) {}
          v.render();
        };
        window.addEventListener("resize", function () {
          if (window.molmanagerResizeKeepView) window.molmanagerResizeKeepView();
        });
      } catch (e) {
        document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
      }
    }
  </script>"""
    return tmpl.replace("__RESET_JS__", _RESET_STRUCTURE_JS)


def _assemble_protein_page(*, script_src: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>html,body,#v{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#fff;}}</style>
</head>
<body>
  <div id="v"></div>
{_reset_structure_menu_html()}
{_viewer_protein_init_script()}
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="{script_src}" onload="molmanagerInitView()"></script>
</body>
</html>"""


def build_protein_viewer_html() -> str:
    """Return the protein 3Dmol page (offline bundle when available)."""
    if bundled_3dmol_available():
        return _assemble_protein_page(script_src="3Dmol-min.js")
    return _assemble_protein_page(script_src="https://3dmol.org/build/3Dmol-min.js")


class _ProteinViewerBridge(QObject):
    atom_picked = pyqtSignal(str)

    @pyqtSlot(str)
    def atomPicked(self, payload: str) -> None:
        self.atom_picked.emit(payload)


class ProteinEmbedView(QWidget):
    """WebEngine host for the protein 3Dmol canvas."""

    atom_picked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_payload: dict | None = None
        self._pending_residue_highlight: list | None = None
        self._pending_pocket: dict | None = None
        self._web = None
        self._bootstrapped = False
        self._bridge = _ProteinViewerBridge(self)
        self._bridge.atom_picked.connect(self.atom_picked.emit)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self.resize_keep_view)
        self._status = QLabel("Open a PDB, mmCIF, or other structure file.", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid); padding: 16px;")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
        self.schedule_resize_keep_view()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._web_ready:
            self.schedule_resize_keep_view()

    def schedule_resize_keep_view(self) -> None:
        self._resize_timer.start()

    def resize_keep_view(self) -> None:
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript(
                "if (window.molmanagerResizeKeepView) window.molmanagerResizeKeepView();"
            )
        except Exception:
            logger.debug("Protein viewer resize-keep-view failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebChannel import QWebChannel
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
            channel = QWebChannel(web.page())
            channel.registerObject("proteinBridge", self._bridge)
            web.page().setWebChannel(channel)
            self._web_channel = channel
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(build_protein_viewer_html(), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(build_protein_viewer_html(), QUrl("https://3dmol.org/"))
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Protein 3D view unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D view unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_payload is not None:
            payload = self._pending_payload
            self._pending_payload = None
            self._run_js("molmanagerSetProteinPayload", payload)
        elif self._web_ready and self._pending_residue_highlight is not None:
            highlight = self._pending_residue_highlight
            self._pending_residue_highlight = None
            self._run_js("molmanagerSetResidueHighlight", highlight)
        if self._web_ready and self._pending_pocket is not None and self._pending_payload is None:
            pocket = self._pending_pocket
            self._pending_pocket = None
            self._run_js("molmanagerSetPocket", pocket)
        if self._web_ready:
            self.schedule_resize_keep_view()
            QTimer.singleShot(200, self.resize_keep_view)

    def _run_js(self, fn_name: str, payload) -> None:
        if self._web is None or not self._web_ready:
            if fn_name == "molmanagerSetProteinPayload":
                self._pending_payload = payload
            elif fn_name == "molmanagerApplyComponentStates" and self._pending_payload is not None:
                self._pending_payload["components"] = payload
            elif fn_name == "molmanagerDeleteComponents" and self._pending_payload is not None:
                drop = set(payload or [])
                self._pending_payload["components"] = [
                    comp
                    for comp in self._pending_payload.get("components") or []
                    if comp.get("id") not in drop
                ]
            elif fn_name == "molmanagerSetResidueHighlight":
                self._pending_residue_highlight = payload
                if self._pending_payload is not None:
                    self._pending_payload["residueHighlight"] = payload
            elif fn_name == "molmanagerSetPocket":
                self._pending_pocket = payload
                if self._pending_payload is not None:
                    self._pending_payload["pocket"] = payload
            return
        js = f"if (window.{fn_name}) window.{fn_name}({json.dumps(payload)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("Protein viewer %s failed", fn_name, exc_info=True)

    def set_payload(self, payload: dict) -> None:
        self._run_js("molmanagerSetProteinPayload", payload)

    def apply_component_states(self, components: list[dict]) -> None:
        self._run_js("molmanagerApplyComponentStates", components)

    def delete_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerDeleteComponents", ids)

    def zoom_to_components(self, ids: list[str]) -> None:
        self._run_js("molmanagerZoomToComponents", ids)

    def set_residue_highlight(self, selections: list[dict]) -> None:
        self._run_js("molmanagerSetResidueHighlight", selections)

    def mutate_residues(self, items: list[dict]) -> None:
        self._run_js("molmanagerMutateResidues", items)

    def delete_residues(self, selections: list[dict]) -> None:
        self._run_js("molmanagerDeleteResidues", selections)

    def zoom_to_selections(self, selections: list[dict]) -> None:
        self._run_js("molmanagerZoomToSelections", selections)

    def set_pocket(self, pocket: dict | None) -> None:
        self._run_js("molmanagerSetPocket", pocket)


class ProteinChainManager(QWidget):
    """Right-hand chain list for selecting components."""

    visibility_changed = pyqtSignal(str, bool)
    selection_changed = pyqtSignal(list)
    focus_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self._syncing = False
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Count"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.focus_requested.emit())
        root.addWidget(self.tree, 1)

    def selected_component_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()

        def _add(cid: str) -> None:
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)

        def _collect(item: QTreeWidgetItem) -> None:
            cid = item.data(0, _ID_ROLE)
            if cid:
                _add(cid)
            for i in range(item.childCount()):
                _collect(item.child(i))

        for item in self.tree.selectedItems():
            _collect(item)
        return ids

    def set_structure(
        self,
        rows: list[_ComponentView],
        *,
        filename: str = "",
        groups: list[tuple[str, str]] | None = None,
    ) -> None:
        self._syncing = True
        self.tree.clear()
        if not rows:
            self._syncing = False
            return
        by_sid: dict[str, list[_ComponentView]] = {}
        if groups:
            for sid, _name in groups:
                by_sid[sid] = []
            for row in rows:
                sid = row.spec.structure_id or (groups[0][0] if groups else "")
                by_sid.setdefault(sid, []).append(row)
            ordered = [(sid, name) for sid, name in groups if by_sid.get(sid)]
        else:
            by_sid[""] = list(rows)
            ordered = [("", filename or "Structure")]
        for sid, name in ordered:
            file_item = QTreeWidgetItem([name, ""])
            file_item.setData(0, _STRUCT_ROLE, sid)
            file_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(file_item)
            slot_rows = by_sid.get(sid) or []
            chain_items: dict[str, QTreeWidgetItem] = {}
            for row in slot_rows:
                chain = (row.spec.chain or "").strip() or "?"
                parent = chain_items.get(chain)
                if parent is None:
                    parent = QTreeWidgetItem([f"Chain {chain}", ""])
                    parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    parent.setData(0, _STRUCT_ROLE, sid)
                    file_item.addChild(parent)
                    chain_items[chain] = parent
                count = (
                    f"{row.spec.n_residues} res"
                    if row.spec.kind in {"polymer", "water"}
                    else f"{row.spec.n_atoms} at"
                )
                item = QTreeWidgetItem([row.spec.label, count])
                item.setData(0, _ID_ROLE, row.spec.component_id)
                item.setData(0, _STRUCT_ROLE, sid)
                item.setData(0, _KIND_ROLE, row.spec.kind)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
                item.setSelected(row.selected)
                parent.addChild(item)
            file_item.setExpanded(True)
        self.tree.expandAll()
        self._syncing = False

    def apply_row_states(self, rows: list[_ComponentView]) -> None:
        """Update checks and selection without rebuilding the tree."""
        by_id = {r.spec.component_id: r for r in rows}
        self._syncing = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                file_item = self.tree.topLevelItem(i)
                for j in range(file_item.childCount()):
                    group = file_item.child(j)
                    for k in range(group.childCount()):
                        item = group.child(k)
                        cid = item.data(0, _ID_ROLE)
                        row = by_id.get(cid)
                        if row is None:
                            continue
                        item.setCheckState(0, Qt.Checked if row.visible else Qt.Unchecked)
                        item.setSelected(row.selected)
        finally:
            self._syncing = False

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0:
            return
        cid = item.data(0, _ID_ROLE)
        visible = item.checkState(0) != Qt.Unchecked
        if cid:
            self.visibility_changed.emit(cid, visible)
            return
        sid = item.data(0, _STRUCT_ROLE)
        if not sid:
            return
        ids: list[str] = []

        def _collect(node: QTreeWidgetItem) -> None:
            child_id = node.data(0, _ID_ROLE)
            if child_id:
                ids.append(child_id)
            for i in range(node.childCount()):
                _collect(node.child(i))

        _collect(item)
        for child_id in ids:
            self.visibility_changed.emit(child_id, visible)

    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        self.selection_changed.emit(self.selected_component_ids())


class ProteinViewerDialog(QDialog):
    """Standalone Protein → Viewer window (3D canvas + chain Manager)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Protein Viewer")
        self.resize(1180, 760)
        make_window_minimizable(self)

        self._slots: list[_LoadedSlot] = []
        self._slot_seq = 0
        self._sequence_chains: list[PolymerChain] = []
        self._sequence_dialog: ProteinSequenceDialog | None = None
        self._prepare_dialog = None
        self._residue_highlight: list[dict] = []
        self._syncing_from_atom = False
        self._pocket_payload_data: dict | None = None
        self._protein_style_actions: dict[str, QAction] = {}
        self._ligand_style_actions: dict[str, QAction] = {}
        self._protein_color_actions: dict[str, QAction] = {}
        self._ligand_color_actions: dict[str, QAction] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("&File")
        act_open = QAction("&Open…", self, triggered=self.open_structure_dialog)
        act_open.setShortcut(QKeySequence.Open)
        file_menu.addAction(act_open)
        act_close = QAction("&Close Structure", self, triggered=self.close_structure)
        file_menu.addAction(act_close)
        act_sequence = QAction("&Sequence", self, triggered=self.open_sequence_window)
        act_sequence.setToolTip("Show the editable amino-acid sequence and select residues in 3D.")
        menubar.addAction(act_sequence)
        act_prepare = QAction("&Prepare…", self, triggered=self.open_prepare_dialog)
        act_prepare.setToolTip(
            "Repair missing atoms, strip waters/heterogens, protonate at pH, and relax with OpenMM."
        )
        menubar.addAction(act_prepare)
        view_menu = menubar.addMenu("&View")
        render_menu = view_menu.addMenu("&Render")
        protein_menu = render_menu.addMenu("&Protein")
        self._protein_style_actions = self._add_render_style_menu(
            protein_menu,
            kind="polymer",
            default="cartoon",
        )
        protein_menu.addSeparator()
        self._protein_color_actions = self._add_render_color_menu(
            protein_menu.addMenu("&Color"),
            kind="polymer",
        )
        ligand_menu = render_menu.addMenu("&Ligand")
        self._ligand_style_actions = self._add_render_style_menu(
            ligand_menu,
            kind="ligand",
            default="ballstick",
        )
        ligand_menu.addSeparator()
        self._ligand_color_actions = self._add_render_color_menu(
            ligand_menu.addMenu("&Color"),
            kind="ligand",
        )
        self._act_pocket = QAction("&Pocket", self)
        self._act_pocket.setToolTip(
            "Zoom to the ligand, show nearby protein residues as ball-and-stick "
            "with residue labels, and display explicit polar hydrogens."
        )
        self._act_pocket.triggered.connect(self._on_pocket)
        view_menu.addAction(self._act_pocket)
        view_menu.addSeparator()
        self._act_all_atoms = QAction("All &Atoms", self)
        self._act_all_atoms.setCheckable(True)
        self._act_all_atoms.setToolTip(
            "Draw protein residues as ball-and-stick (all atoms) instead of a ribbon cartoon."
        )
        self._act_all_atoms.toggled.connect(self._on_all_atoms_toggled)
        view_menu.addAction(self._act_all_atoms)
        view_menu.addSeparator()
        view_menu.addAction(QAction("Reset Camera", self, triggered=self._reset_camera))
        select_menu = menubar.addMenu("&Select")
        act_hide = QAction("&Hide", self, triggered=lambda: self._set_selected_visible(False))
        act_hide.setToolTip("Hide the chains selected in the Manager.")
        select_menu.addAction(act_hide)
        act_show = QAction("&Show", self, triggered=lambda: self._set_selected_visible(True))
        act_show.setToolTip("Show the chains selected in the Manager.")
        select_menu.addAction(act_show)
        act_focus = QAction("&Focus", self, triggered=self.focus_selected)
        act_focus.setToolTip("Zoom the 3D view to the Manager selection.")
        select_menu.addAction(act_focus)
        act_delete = QAction("&Delete", self, triggered=self.delete_selected)
        act_delete.setToolTip("Remove the Manager selection from the viewer.")
        select_menu.addAction(act_delete)
        select_menu.addSeparator()
        self._add_select_style_menu(select_menu.addMenu("&Render"))
        self._add_select_color_menu(select_menu.addMenu("&Color"))
        root.setMenuBar(menubar)

        splitter = QSplitter(Qt.Horizontal)
        self.viewer = ProteinEmbedView(self)
        self.viewer.atom_picked.connect(self._on_atom_picked)
        self.manager = ProteinChainManager(self)
        self.manager.visibility_changed.connect(self._on_visibility_changed)
        self.manager.selection_changed.connect(self._on_manager_selection)
        self.manager.focus_requested.connect(self.focus_selected)
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.manager)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([860, 300])
        root.addWidget(splitter, 1)

        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.delete_selected)

    @property
    def _rows(self) -> list[_ComponentView]:
        return [row for slot in self._slots for row in slot.rows]

    @property
    def _loaded(self) -> LoadedStructure | None:
        slot = self._active_slot()
        if slot is None:
            return None
        return LoadedStructure(
            path=slot.path,
            text=slot.text,
            sniffed_format=slot.fmt,
            viewer_format=slot.fmt,
            components=tuple(row.spec for row in slot.rows),
        )

    @property
    def _viewer_text(self) -> str:
        slot = self._active_slot()
        return slot.text if slot is not None else ""

    @property
    def _viewer_fmt(self) -> str:
        slot = self._active_slot()
        return slot.fmt if slot is not None else "pdb"

    def _active_slot(self) -> _LoadedSlot | None:
        selected = [r.spec.structure_id for r in self._rows if r.selected]
        if selected:
            sid = selected[-1]
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        if self._slots:
            return self._slots[-1]
        return None

    def _manager_groups(self) -> list[tuple[str, str]]:
        return [(slot.structure_id, slot.name) for slot in self._slots]

    def _refresh_manager(self) -> None:
        names = [slot.name for slot in self._slots]
        filename = ", ".join(names) if names else ""
        self.manager.set_structure(self._rows, filename=filename, groups=self._manager_groups())
        if len(names) == 1:
            self.setWindowTitle(f"Protein Viewer — {names[0]}")
        elif names:
            self.setWindowTitle(f"Protein Viewer — {len(names)} structures")
        else:
            self.setWindowTitle("Protein Viewer")

    def _unique_slot_name(self, name: str) -> str:
        used = {slot.name for slot in self._slots}
        if name not in used:
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        n = 2
        while True:
            candidate = f"{stem} ({n}){suffix}"
            if candidate not in used:
                return candidate
            n += 1

    def prepare_source(self) -> tuple[str, str, str, Path | None]:
        """Return (display name, file text, viewer format, path) for Prepare."""
        slot = self._active_slot()
        if slot is None:
            return ("", "", "pdb", None)
        return (slot.name, slot.text, slot.fmt, slot.path)

    def prepare_water_keys(self) -> tuple[tuple[str, str, str], ...]:
        """Residue keys for Manager-selected water groups on the active structure."""
        slot = self._active_slot()
        if slot is None:
            return ()
        selected_chains = {
            row.spec.chain
            for row in slot.rows
            if row.selected and row.spec.kind == "water" and row.spec.chain
        }
        if not selected_chains:
            return ()
        keys: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for poly in parse_polymer_sequences(slot.text, slot.fmt):
            if poly.chain not in selected_chains:
                continue
            for res in poly.residues:
                if res.kind != "water":
                    continue
                key = (res.chain, res.resi, res.icode)
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return tuple(keys)

    def open_structure_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open structure", "", STRUCTURE_FILE_FILTER)
        for i, path in enumerate(paths):
            self.add_structure_path(path, refit=(i == len(paths) - 1))

    def load_structure_path(self, path: str | Path) -> None:
        self.add_structure_path(path, refit=True)

    def add_structure_path(self, path: str | Path, *, refit: bool = True) -> None:
        try:
            loaded = load_structure_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Protein Viewer", str(exc))
            return
        text = loaded.text
        fmt = loaded.viewer_format
        if loaded.sniffed_format == "pdbqt":
            from .dock_complex_viewer import pdbqt_to_pdb_text

            text = pdbqt_to_pdb_text(loaded.text) or loaded.text
            fmt = "pdb"
        if not loaded.components:
            QMessageBox.information(
                self,
                "Protein Viewer",
                "No atoms were found in that file.",
            )
            return
        sid = f"s{self._slot_seq}"
        self._slot_seq += 1
        model = len(self._slots)
        protein_style = self._checked_style(self._protein_style_actions, "cartoon")
        ligand_style = self._checked_style(self._ligand_style_actions, "ballstick")
        protein_color = self._checked_style(self._protein_color_actions, "default")
        ligand_color = self._checked_style(self._ligand_color_actions, "default")
        rows = [
            _ComponentView(
                spec=scope_structure_component(comp, structure_id=sid, model=model),
                visible=comp.default_visible,
                selected=False,
                style=(
                    protein_style
                    if comp.kind == "polymer"
                    else ligand_style
                    if comp.kind == "ligand"
                    else comp.default_style
                ),
                color_scheme=(
                    protein_color
                    if comp.kind == "polymer"
                    else ligand_color
                    if comp.kind == "ligand"
                    else "default"
                ),
            )
            for comp in loaded.components
        ]
        self._slots.append(
            _LoadedSlot(
                structure_id=sid,
                name=self._unique_slot_name(loaded.path.name),
                path=loaded.path,
                text=text,
                fmt=fmt,
                rows=rows,
            )
        )
        self._residue_highlight = []
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=refit)
        if self._pocket_payload_data is not None:
            self._refresh_pocket(zoom=False)

    def _reindex_models(self) -> None:
        for model, slot in enumerate(self._slots):
            slot.rows = [
                replace(
                    row,
                    spec=scope_structure_component(
                        row.spec, structure_id=slot.structure_id, model=model
                    ),
                )
                for row in slot.rows
            ]

    def close_structure(self) -> None:
        self._slots = []
        self._sequence_chains = []
        self._residue_highlight = []
        self._pocket_payload_data = None
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(False)
        self._act_all_atoms.blockSignals(False)
        self._check_style_action(self._protein_style_actions, "cartoon")
        self._check_style_action(self._ligand_style_actions, "ballstick")
        self._check_style_action(self._protein_color_actions, "default")
        self._check_style_action(self._ligand_color_actions, "default")
        self.setWindowTitle("Protein Viewer")
        self.manager.set_structure([])
        self._sync_sequence_dialog()
        self.viewer.set_payload(
            {
                "data": "",
                "fmt": "pdb",
                "models": [],
                "components": [],
                "residueHighlight": [],
                "pocket": None,
                "refit": True,
            }
        )

    def open_prepare_dialog(self) -> None:
        """Open the Prepare pipeline dialog for the loaded structure."""
        if not self._slots:
            QMessageBox.information(self, "Prepare Structure", "Open a structure first.")
            return
        dlg = self._prepare_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._prepare_dialog = None
            dlg = None
        if dlg is None:
            from .protein_prepare_dialog import ProteinPrepareDialog

            dlg = ProteinPrepareDialog(self)
            dlg.prepared.connect(self._on_structure_prepared)
            dlg.destroyed.connect(self._on_prepare_dialog_destroyed)
            self._prepare_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_prepare_dialog_destroyed(self) -> None:
        self._prepare_dialog = None

    def _on_structure_prepared(self, output_pdb: str) -> None:
        path = Path(output_pdb)
        if not path.is_file():
            QMessageBox.warning(self, "Prepare Structure", f"Prepared file was not found:\n{path}")
            return
        self.add_structure_path(path, refit=False)

    def open_sequence_window(self) -> None:
        """Open or raise the Sequence window for the current polymer chains."""
        dlg = self._sequence_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._sequence_dialog = None
            dlg = None
        if dlg is None:
            dlg = ProteinSequenceDialog(self)
            dlg.residue_selection_changed.connect(self._on_sequence_selection)
            dlg.residues_mutated.connect(self._on_sequence_mutated)
            dlg.residues_deleted.connect(self._on_sequence_deleted)
            dlg.focus_residues_requested.connect(self._on_sequence_focus)
            dlg.destroyed.connect(self._on_sequence_dialog_destroyed)
            self._sequence_dialog = dlg
        dlg.set_chains(self._sequence_chains)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_sequence_dialog_destroyed(self) -> None:
        self._sequence_dialog = None

    def _refresh_sequence_chains(self) -> None:
        filtered: list[PolymerChain] = []
        for model, slot in enumerate(self._slots):
            fmt = "cif" if slot.fmt == "cif" else "pdb"
            for poly in parse_polymer_sequences(slot.text, fmt):
                residues = [
                    replace(
                        res,
                        structure_id=slot.structure_id,
                        model=model,
                    )
                    for res in poly.residues
                    if self._sequence_residue_is_live(res, slot)
                ]
                if residues:
                    filtered.append(
                        PolymerChain(
                            chain=poly.chain,
                            residues=list(residues),
                            structure_id=slot.structure_id,
                            structure_name=slot.name,
                        )
                    )
        self._sequence_chains = filtered
        self._sync_sequence_dialog()

    def _sequence_residue_is_live(self, res, slot: _LoadedSlot) -> bool:
        rows = slot.rows
        if not rows:
            return False
        if res.kind in {"polymer", "missing"}:
            return any(row.spec.kind == "polymer" and row.spec.chain == res.chain for row in rows)
        if res.kind == "water":
            return any(row.spec.kind == "water" and row.spec.chain == res.chain for row in rows)
        return any(
            row.spec.kind == res.kind
            and row.spec.chain == res.chain
            and row.spec.resn == res.resn
            and row.spec.resi == res.resi
            for row in rows
        )

    def _on_all_atoms_toggled(self, checked: bool) -> None:
        style = "ballstick" if checked else "cartoon"
        self._check_style_action(self._protein_style_actions, style)
        self._apply_kind_style("polymer", style)

    def _apply_kind_style(self, kind: str, style: str) -> None:
        allowed = {key for key, _label in COMPONENT_STYLE_CHOICES}
        if style not in allowed:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.style != style:
                    new_rows.append(replace(row, style=style))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _add_select_style_menu(self, menu) -> None:
        for style_id, label in COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Apply this style to the Manager selection.")
            act.triggered.connect(lambda _checked=False, s=style_id: self._on_style_requested(s))
            menu.addAction(act)

    def _add_select_color_menu(self, menu) -> None:
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Color carbons in the Manager selection; heteroatoms stay CPK.")
            act.triggered.connect(lambda _checked=False, c=color_id: self._apply_selected_color(c))
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("Custom…", self, triggered=self._on_select_custom_color)
        act_custom.setToolTip("Pick a carbon color for the Manager selection.")
        menu.addAction(act_custom)

    def _selected_component_ids(self) -> list[str]:
        return self.manager.selected_component_ids() or [
            r.spec.component_id for r in self._rows if r.selected
        ]

    def _require_selection(self) -> list[str]:
        ids = self._selected_component_ids()
        if not ids:
            QMessageBox.information(
                self,
                "Select",
                "Select a chain or ligand in the Manager first.",
            )
        return ids

    def _set_selected_visible(self, visible: bool) -> None:
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_select_custom_color(self) -> None:
        chosen = QColorDialog.getColor(QColor("#2ca02c"), self, "Carbon color")
        if not chosen.isValid():
            return
        self._apply_selected_color(chosen.name())

    def _apply_selected_color(self, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed and not str(color_scheme).startswith("#"):
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()

    def _add_render_style_menu(self, menu, *, kind: str, default: str) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for style_id, label in COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(style_id)
            if style_id == default:
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, s=style_id, k=kind: self._on_render_style_chosen(k, s)
            )
            actions[style_id] = act
        return actions

    def _add_render_color_menu(self, menu, *, kind: str) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(color_id)
            if color_id == "default":
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, c=color_id, k=kind: self._on_render_color_chosen(k, c)
            )
            actions[color_id] = act
        return actions

    def _on_render_style_chosen(self, kind: str, style: str) -> None:
        self._apply_kind_style(kind, style)
        if kind == "polymer":
            self._sync_all_atoms_check(style == "ballstick")

    def _on_render_color_chosen(self, kind: str, color_scheme: str) -> None:
        self._apply_kind_color(kind, color_scheme)

    def _apply_kind_color(self, kind: str, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()

    def _checked_style(self, actions: dict[str, QAction], fallback: str) -> str:
        for style_id, act in actions.items():
            if act.isChecked():
                return style_id
        return fallback

    def _check_style_action(self, actions: dict[str, QAction], style: str) -> None:
        act = actions.get(style)
        if act is None or act.isChecked():
            return
        act.blockSignals(True)
        act.setChecked(True)
        act.blockSignals(False)

    def _sync_all_atoms_check(self, checked: bool) -> None:
        if self._act_all_atoms.isChecked() == checked:
            return
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(checked)
        self._act_all_atoms.blockSignals(False)

    def _sync_render_menus_from_rows(self) -> None:
        polymer = {r.style for r in self._rows if r.spec.kind == "polymer"}
        ligand = {r.style for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer) == 1:
            style = next(iter(polymer))
            self._check_style_action(self._protein_style_actions, style)
            self._sync_all_atoms_check(style == "ballstick")
        if len(ligand) == 1:
            self._check_style_action(self._ligand_style_actions, next(iter(ligand)))
        polymer_color = {r.color_scheme for r in self._rows if r.spec.kind == "polymer"}
        ligand_color = {r.color_scheme for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer_color) == 1:
            self._check_style_action(self._protein_color_actions, next(iter(polymer_color)))
        if len(ligand_color) == 1:
            self._check_style_action(self._ligand_color_actions, next(iter(ligand_color)))

    def _on_pocket(self) -> None:
        self._activate_pocket(zoom=True)

    def _activate_pocket(self, *, zoom: bool) -> bool:
        payload = self._compute_pocket_payload()
        if payload is None:
            if zoom:
                QMessageBox.information(
                    self,
                    "Pocket",
                    "Open a structure that contains a ligand, or select a ligand in the Manager.",
                )
            return False
        self._pocket_payload_data = payload
        self.viewer.set_pocket(payload)
        if zoom:
            sels = payload.get("zoomSels") or []
            if sels:
                self.viewer.zoom_to_selections(sels)
        return True

    def _refresh_pocket(self, *, zoom: bool) -> None:
        if self._pocket_payload_data is None:
            return
        if self._activate_pocket(zoom=zoom):
            return
        self._pocket_payload_data = None
        self.viewer.set_pocket({"active": False})

    def _compute_pocket_payload(self) -> dict | None:
        selected_ligands = [r for r in self._rows if r.selected and r.spec.kind == "ligand"]
        if selected_ligands:
            sid = selected_ligands[0].spec.structure_id
            slot = next((s for s in self._slots if s.structure_id == sid), None)
            lig_rows = [r for r in selected_ligands if r.spec.structure_id == sid]
        else:
            slot = self._active_slot()
            lig_rows = [r for r in (slot.rows if slot else []) if r.spec.kind == "ligand"]
        if slot is None or not lig_rows:
            return None
        model = None
        for row in lig_rows:
            model = (row.spec.selection or {}).get("model")
            if model is not None:
                break
        keys = [(r.spec.chain, r.spec.resn, r.spec.resi, r.spec.icode) for r in lig_rows]
        plan = pocket_view_plan(slot.text, slot.fmt, ligand_keys=keys, model=model)
        if plan is None:
            return None
        polar_b64 = ""
        if plan.polar_h_pdb:
            polar_b64 = base64.b64encode(plan.polar_h_pdb.encode("utf-8")).decode("ascii")
        return {
            "active": True,
            "ligandSels": list(plan.ligand_sels),
            "residueSels": list(plan.residue_sels),
            "zoomSels": list(plan.ligand_sels),
            "polarHPdb": polar_b64,
        }

    def _sync_sequence_dialog(self) -> None:
        dlg = self._sequence_dialog
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_chains(self._sequence_chains)

    def _set_residue_highlight(self, selections: list[dict]) -> None:
        self._residue_highlight = list(selections)
        self.viewer.set_residue_highlight(self._residue_highlight)

    def _on_sequence_selection(self, selections: list) -> None:
        self._set_residue_highlight(list(selections or []))

    def _on_sequence_focus(self, selections: list) -> None:
        if selections:
            self.viewer.zoom_to_selections(list(selections))

    def _slot_for_residue(self, residue) -> _LoadedSlot | None:
        sid = getattr(residue, "structure_id", "") or ""
        if sid:
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        return self._active_slot()

    def _on_sequence_mutated(self, items: list) -> None:
        payload = []
        by_slot: dict[str, list[tuple[str, str, str, str]]] = {}
        for residue, letter in items:
            resn = letter_to_resn(letter)
            if not resn:
                continue
            entry = {
                "chain": residue.chain,
                "resi": residue.selection().get("resi"),
                "icode": residue.icode,
                "resn": resn,
            }
            if residue.model is not None:
                entry["model"] = residue.model
            payload.append(entry)
            slot = self._slot_for_residue(residue)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, []).append(
                (residue.chain, residue.resi, residue.icode, resn)
            )
        if not payload:
            return
        for slot in self._slots:
            changes = by_slot.get(slot.structure_id)
            if changes and slot.fmt in {"pdb", "pqr"}:
                slot.text = rewrite_pdb_residue_names(slot.text, changes)
        self.viewer.mutate_residues(payload)
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()

    def _on_sequence_deleted(self, residues: list) -> None:
        if not residues:
            return
        keys = {(res.chain, res.resi, res.icode) for res in residues}
        sels = [res.selection() for res in residues]
        by_slot: dict[str, set[tuple[str, str, str]]] = {}
        for res in residues:
            slot = self._slot_for_residue(res)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, set()).add((res.chain, res.resi, res.icode))
        for slot in self._slots:
            slot_keys = by_slot.get(slot.structure_id)
            if slot_keys and slot.fmt in {"pdb", "pqr"}:
                slot.text = delete_pdb_residues(slot.text, slot_keys)
        self.viewer.delete_residues(sels)
        self._residue_highlight = [
            sel
            for sel in self._residue_highlight
            if (str(sel.get("chain")), str(sel.get("resi")), str(sel.get("icode") or ""))
            not in {(k[0], k[1], k[2]) for k in keys}
        ]
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()
        self.viewer.set_residue_highlight(self._residue_highlight)

    def delete_selected(self) -> None:
        ids = self._selected_component_ids()
        if not ids:
            return
        labels = [r.spec.label for r in self._rows if r.spec.component_id in set(ids)]
        preview = ", ".join(labels[:6])
        if len(labels) > 6:
            preview += "…"
        n = len(ids)
        msg = f"Delete {n} selected chain{'s' if n != 1 else ''} from the viewer?"
        if preview:
            msg += f"\n\n{preview}"
        if (
            QMessageBox.question(
                self, "Delete chains", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            != QMessageBox.Yes
        ):
            return
        drop = set(ids)
        kept: list[_LoadedSlot] = []
        for slot in self._slots:
            rows = [r for r in slot.rows if r.spec.component_id not in drop]
            if rows:
                slot.rows = rows
                kept.append(slot)
        self._slots = kept
        self._reindex_models()
        if not self._slots:
            self.close_structure()
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=False)
        if self._pocket_payload_data is not None:
            self._refresh_pocket(zoom=False)

    def focus_selected(self) -> None:
        ids = self._require_selection()
        if ids:
            self.viewer.zoom_to_components(ids)

    def _on_visibility_changed(self, component_id: str, visible: bool) -> None:
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id == component_id and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_manager_selection(self, ids: list) -> None:
        want = set(ids)
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                selected = row.spec.component_id in want
                if row.selected != selected:
                    new_rows.append(replace(row, selected=selected))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if not self._syncing_from_atom and self._residue_highlight:
            self._residue_highlight = []
            self.viewer.set_residue_highlight([])
        if changed:
            self._push_states()

    def _on_style_requested(self, style: str) -> None:
        allowed = {key for key, _label in COMPONENT_STYLE_CHOICES}
        if style not in allowed:
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.style != style:
                    new_rows.append(replace(row, style=style))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self._push_states()
            self._sync_render_menus_from_rows()

    def _on_atom_picked(self, payload: str) -> None:
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return
        model = data.get("model")
        try:
            model_i = int(model) if model is not None and str(model).strip() != "" else None
        except (TypeError, ValueError):
            model_i = None
        cid = component_id_for_atom(
            (r.spec for r in self._rows),
            chain=str(data.get("chain") or ""),
            resn=str(data.get("resn") or ""),
            resi=data.get("resi"),
            icode=str(data.get("icode") or ""),
            model=model_i,
        )
        if not cid:
            return
        sel = {
            "chain": str(data.get("chain") or ""),
            "resi": data.get("resi"),
        }
        icode = str(data.get("icode") or "")
        if icode:
            sel["icode"] = icode
        if model_i is not None:
            sel["model"] = model_i
        try:
            sel["resi"] = int(str(sel["resi"]).strip())
        except (TypeError, ValueError):
            sel["resi"] = str(sel.get("resi") or "")
        self._syncing_from_atom = True
        try:
            for slot in self._slots:
                slot.rows = [
                    replace(row, selected=row.spec.component_id == cid) for row in slot.rows
                ]
            self.manager.apply_row_states(self._rows)
            self._set_residue_highlight([sel])
            self._push_states()
        finally:
            self._syncing_from_atom = False
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            spec = next((r.spec for r in self._rows if r.spec.component_id == cid), None)
            hit = polymer_residue_for_atom(
                self._sequence_chains,
                chain=str(data.get("chain") or ""),
                resi=data.get("resi"),
                icode=icode,
                structure_id=spec.structure_id if spec is not None else "",
            )
            if hit is not None:
                dlg.select_residue(hit.chain, hit.resi, hit.icode, structure_id=hit.structure_id)

    def _reset_camera(self) -> None:
        web = getattr(self.viewer, "_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(
                "if (window.molmanagerResetStructure) window.molmanagerResetStructure();"
            )
        except Exception:
            logger.debug("Protein viewer reset camera failed", exc_info=True)

    def _component_payloads(self) -> list[dict]:
        out: list[dict] = []
        for row in self._rows:
            payload = row.spec.to_payload()
            payload["visible"] = row.visible
            payload["selected"] = row.selected
            payload["style"] = row.style
            scheme = row.color_scheme or "default"
            spec = _RENDER_COLOR_SPEC.get(scheme)
            if spec is not None:
                payload["cartoonColor"] = spec[0]
                payload["carbonScheme"] = spec[1]
            elif str(scheme).startswith("#"):
                payload["cartoonColor"] = scheme
                payload["carbonScheme"] = scheme
            out.append(payload)
        return out

    def _push_structure(self, *, refit: bool) -> None:
        models = []
        for slot in self._slots:
            model = {
                "data": base64.b64encode(slot.text.encode("utf-8")).decode("ascii"),
                "fmt": slot.fmt,
                "name": slot.name,
            }
            if slot.fmt == "cif":
                tables = cif_viewer_bond_tables(slot.text)
                if tables:
                    model["cifBonds"] = tables
            models.append(model)
        self.viewer.set_payload(
            {
                "models": models,
                "fmt": models[0]["fmt"] if models else "pdb",
                "data": models[0]["data"] if models else "",
                "components": self._component_payloads(),
                "residueHighlight": self._residue_highlight,
                "pocket": self._pocket_payload_data,
                "refit": bool(refit),
            }
        )

    def _push_states(self) -> None:
        self.viewer.apply_component_states(self._component_payloads())
