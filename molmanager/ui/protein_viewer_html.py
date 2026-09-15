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


"""3Dmol.js page assembly for the protein viewer."""

from __future__ import annotations


from .mol_3d_html import (
    _RESET_STRUCTURE_JS,
    assemble_3dmol_shell_page,
    bundled_3dmol_available,
)


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
          applyResidueHighlight(v);
          applyHydrogenVisibility(v);
          applyPocketOverlay(v);
          applyHydrogenBonds(v);
        }
        function isHydrogenAtom(at) {
          var e = String((at && at.elem) || "").toUpperCase();
          return e === "H" || e === "D";
        }
        function atomModelId(at) {
          if (at && at.model && typeof at.model.id === "number") return at.model.id;
          if (typeof at.model === "number") return at.model;
          return 0;
        }
        function polarHeavy(elem) {
          var e = String(elem || "").toUpperCase();
          return e === "N" || e === "O" || e === "S" || e === "F";
        }
        function bondedAtom(at, bondRef) {
          if (bondRef && typeof bondRef === "object" && bondRef.elem != null) return bondRef;
          var idx = typeof bondRef === "number" ? bondRef : parseInt(bondRef, 10);
          if (isNaN(idx)) return null;
          var model = at && at.model;
          if (model && model.atoms && model.atoms[idx]) return model.atoms[idx];
          return null;
        }
        function nearestSameResidueHeavy(at, atoms) {
          var best = null;
          var bestD = 1.35 * 1.35;
          for (var i = 0; i < atoms.length; i++) {
            var o = atoms[i];
            if (!o || o === at || isHydrogenAtom(o)) continue;
            if ((o.chain || "") !== (at.chain || "")) continue;
            if (String(o.resi) !== String(at.resi)) continue;
            if ((o.icode || "") !== (at.icode || "")) continue;
            if (atomModelId(o) !== atomModelId(at)) continue;
            var dx = o.x - at.x, dy = o.y - at.y, dz = o.z - at.z;
            var d = dx * dx + dy * dy + dz * dz;
            if (d <= bestD) { bestD = d; best = o; }
          }
          return best;
        }
        function hydrogenParentIsPolar(at, atoms) {
          var bonds = at.bonds || [];
          if (bonds.length) {
            for (var i = 0; i < bonds.length; i++) {
              var other = bondedAtom(at, bonds[i]);
              if (other && polarHeavy(other.elem)) return true;
            }
            return false;
          }
          var parent = nearestSameResidueHeavy(at, atoms);
          return !!(parent && polarHeavy(parent.elem));
        }
        function hideAtom(v, at) {
          try {
            v.addStyle({model: atomModelId(at), serial: at.serial}, {hidden: true});
          } catch (eHideAt) {}
        }
        function applyHydrogenVisibility(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          if (window.molmanagerHydrogens === "all") return;
          var atoms;
          try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
          if (!atoms || !atoms.length) return;
          for (var i = 0; i < atoms.length; i++) {
            var at = atoms[i];
            if (!isHydrogenAtom(at)) continue;
            if (hydrogenParentIsPolar(at, atoms)) continue;
            hideAtom(v, at);
          }
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
              var pocketAtoms = v.selectedAtoms(sel);
              for (var pi = 0; pi < pocketAtoms.length; pi++) {
                if (isHydrogenAtom(pocketAtoms[pi])) hideAtom(v, pocketAtoms[pi]);
              }
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
        function applyHydrogenBonds(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          try { v.removeAllShapes(); } catch (eSh) {}
          var spec = window.molmanagerHbonds;
          if (!spec || !spec.active || !spec.bonds || !spec.bonds.length) return;
          for (var i = 0; i < spec.bonds.length; i++) {
            var b = spec.bonds[i] || {};
            var start = b.start || {};
            var end = b.end || {};
            var color = b.color || "#E6C229";
            try {
              v.addCylinder({
                start: {x: start.x, y: start.y, z: start.z},
                end: {x: end.x, y: end.y, z: end.z},
                radius: 0.06,
                fromCap: 2,
                toCap: 2,
                dashed: true,
                dashLength: 0.22,
                gapLength: 0.14,
                color: color
              });
            } catch (eCyl) {
              try {
                v.addLine({
                  dashed: true,
                  start: {x: start.x, y: start.y, z: start.z},
                  end: {x: end.x, y: end.y, z: end.z},
                  color: color
                });
              } catch (eLn) {}
            }
          }
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
        window.molmanagerHydrogens = "polar";
        window.molmanagerHbonds = null;
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
          window.molmanagerHbonds = payload.hbonds || null;
          if (payload.hydrogens) {
            window.molmanagerHydrogens = payload.hydrogens === "all" ? "all" : "polar";
          }
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
        window.molmanagerSetHydrogens = function (mode) {
          window.molmanagerHydrogens = mode === "all" ? "all" : "polar";
          if (!window.molmanagerViewer) return;
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerSetHbonds = function (spec) {
          window.molmanagerHbonds = spec || null;
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
    return assemble_3dmol_shell_page(
        script_src=script_src,
        init_html=_viewer_protein_init_script(),
        extra_scripts='  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n',
        background="#fff",
    )


def build_protein_viewer_html() -> str:
    """Return the protein 3Dmol page (offline bundle when available)."""
    if bundled_3dmol_available():
        return _assemble_protein_page(script_src="3Dmol-min.js")
    return _assemble_protein_page(script_src="https://3dmol.org/build/3Dmol-min.js")
