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
                v.addStyle(sel, {stick: {radius: 0.18, color: "orange"}});
              }
            } catch (eSel) {}
          }
        }
        function applyResidueHighlight(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var sels = window.molmanagerResidueHighlight || [];
          if (!sels.length) return;
          var residueParts = [];
          var atomParts = [];
          for (var i = 0; i < sels.length; i++) {
            var src = sels[i] || {};
            if ((src.serial != null && src.serial !== "") || src.atom) {
              var asel = {};
              if (src.model != null && src.model !== "") asel.model = src.model;
              if (src.serial != null && src.serial !== "") asel.serial = src.serial;
              else {
                if (src.chain) asel.chain = src.chain;
                if (src.resi != null && src.resi !== "") asel.resi = src.resi;
                if (src.icode) asel.icode = src.icode;
                if (src.atom) asel.atom = src.atom;
              }
              atomParts.push(asel);
            } else {
              residueParts.push(src);
            }
          }
          if (residueParts.length) {
            var sel = residueParts.length === 1 ? residueParts[0] : {or: residueParts};
            try {
              v.addStyle(sel, {cartoon: {color: "orange"}});
              v.addStyle(sel, {stick: {radius: 0.18, color: "orange"}, sphere: {scale: 0.26}});
            } catch (eHi) {}
          }
          for (var j = 0; j < atomParts.length; j++) {
            var atomSel = atomParts[j];
            try {
              v.addStyle(atomSel, {
                sphere: {scale: 0.28, color: "orange"},
                stick: {radius: 0.16, color: "orange"}
              });
            } catch (eAt) {}
            try {
              var picked = v.selectedAtoms(atomSel);
              if (picked && picked[0] && typeof v.addLabel === "function") {
                var at = picked[0];
                var bits = [];
                if (at.chain) bits.push(at.chain);
                if (at.resn) bits.push(at.resn);
                if (at.resi != null && at.resi !== "") bits.push(String(at.resi));
                if (at.atom) bits.push(at.atom);
                var text = bits.join(" ");
                if (text) {
                  v.addLabel(text, {
                    position: at,
                    fontSize: 11,
                    fontColor: "black",
                    backgroundColor: "white",
                    backgroundOpacity: 0.82,
                    inFront: true
                  });
                }
              }
            } catch (eLab) {}
          }
        }
        function atomBondIndex(at) {
          if (!at) return null;
          return (typeof at.index === "number") ? at.index : at;
        }
        function partnerIndex(atom, other) {
          if (!atom || !atom.bonds) return -1;
          var want = atomBondIndex(other);
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
        function removeBond(a, b) {
          if (!a || !b) return;
          function strip(atom, other) {
            if (!atom || !atom.bonds) return;
            var want = atomBondIndex(other);
            var nextB = [];
            var nextO = [];
            for (var i = 0; i < atom.bonds.length; i++) {
              var partner = atom.bonds[i];
              if (atomBondIndex(partner) === want || partner === other) continue;
              nextB.push(partner);
              if (atom.bondOrder) nextO.push(atom.bondOrder[i]);
            }
            atom.bonds = nextB;
            if (atom.bondOrder) atom.bondOrder = nextO;
          }
          strip(a, b);
          strip(b, a);
        }
        function atomIsHydrogen(at) {
          if (!at) return false;
          var el = String(at.elem || at.element || "").toUpperCase();
          return el === "H" || el === "D" || el === "T";
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
            if (!Object.prototype.hasOwnProperty.call(tables, resn)) continue;
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
          for (var gk in groups) {
            if (!Object.prototype.hasOwnProperty.call(groups, gk)) continue;
            var g = groups[gk];
            var groupAtoms = [];
            for (var nm in g.byName) {
              if (!Object.prototype.hasOwnProperty.call(g.byName, nm)) continue;
              var named = g.byName[nm];
              for (var gi = 0; gi < named.length; gi++) groupAtoms.push(named[gi]);
            }
            var inGroup = {};
            for (var ga = 0; ga < groupAtoms.length; ga++) {
              inGroup[atomBondIndex(groupAtoms[ga])] = true;
            }
            var byIndex = {};
            for (var ga = 0; ga < groupAtoms.length; ga++) {
              byIndex[atomBondIndex(groupAtoms[ga])] = groupAtoms[ga];
            }
            for (var gb = 0; gb < groupAtoms.length; gb++) {
              var atom = groupAtoms[gb];
              if (!atom.bonds) continue;
              var keepB = [];
              var keepO = [];
              for (var bi = 0; bi < atom.bonds.length; bi++) {
                var partner = atom.bonds[bi];
                var other = (partner && typeof partner === "object")
                  ? partner
                  : byIndex[atomBondIndex(partner)];
                // Keep 3Dmol's distance H–X bonds. Amber/OpenMM often rename
                // hydrogens while copied _chem_comp_bond rows keep old H ids.
                if (atomIsHydrogen(atom) || atomIsHydrogen(other) || !inGroup[atomBondIndex(partner)]) {
                  keepB.push(partner);
                  if (atom.bondOrder) keepO.push(atom.bondOrder[bi]);
                }
              }
              atom.bonds = keepB;
              if (atom.bondOrder) atom.bondOrder = keepO;
            }
            var bonds = tables[g.resn] || [];
            for (var bj = 0; bj < bonds.length; bj++) {
              var pair = bonds[bj];
              if (!pair || pair.length < 3) continue;
              var a1 = pick(g.byName[normName(pair[0])]);
              var a2 = pick(g.byName[normName(pair[1])]);
              var ord = parseInt(pair[2], 10);
              if (!a1 || !a2 || !(ord >= 1)) continue;
              if (atomIsHydrogen(a1) || atomIsHydrogen(a2)) continue;
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
          try { v.removeAllShapes(); } catch (eSh) {}
          var comps = window.molmanagerComponents || [];
          for (var i = 0; i < comps.length; i++) applyOneStyle(v, comps[i]);
          applyResidueHighlight(v);
          applyPocketOverlay(v);
          applyPocketSurface(v);
          applyHydrogenVisibility(v);
          applyHydrogenBonds(v);
          applyDockingBox(v);
          applyDockPose(v);
          bindPicking(v);
        }
        function isHydrogenAtom(at) {
          var e = String((at && at.elem) || "").toUpperCase();
          return e === "H" || e === "D" || e === "T";
        }
        function atomModelId(at) {
          if (at && at.model && typeof at.model.id === "number") return at.model.id;
          if (typeof at.model === "number") return at.model;
          return 0;
        }
        function polarHeavy(elem) {
          var e = String(elem || "").toUpperCase();
          return !!e && e !== "C" && e !== "H" && e !== "D" && e !== "T";
        }
        function bondedAtom(at, bondRef) {
          if (bondRef && typeof bondRef === "object" && bondRef.elem != null) return bondRef;
          var idx = typeof bondRef === "number" ? bondRef : parseInt(bondRef, 10);
          if (isNaN(idx)) return null;
          var model = at && at.model;
          if (model && model.atoms && model.atoms[idx]) return model.atoms[idx];
          return null;
        }
        function residueHeavyKey(at) {
          return atomModelId(at) + "\t" + (at.chain || "") + "\t"
            + (at.resi == null ? "" : String(at.resi)) + "\t" + (at.icode || "");
        }
        function indexResidueHeavies(atoms) {
          var idx = {};
          for (var i = 0; i < atoms.length; i++) {
            var o = atoms[i];
            if (!o || isHydrogenAtom(o)) continue;
            var key = residueHeavyKey(o);
            if (!idx[key]) idx[key] = [];
            idx[key].push(o);
          }
          return idx;
        }
        function hydrogenParentIsPolar(at, heavyIndex) {
          var bonds = at.bonds || [];
          for (var i = 0; i < bonds.length; i++) {
            var other = bondedAtom(at, bonds[i]);
            if (other && polarHeavy(other.elem)) return true;
          }
          var list = (heavyIndex && heavyIndex[residueHeavyKey(at)]) || [];
          var lim = 1.5 * 1.5;
          for (var j = 0; j < list.length; j++) {
            var o = list[j];
            if (!polarHeavy(o.elem)) continue;
            var dx = o.x - at.x, dy = o.y - at.y, dz = o.z - at.z;
            if ((dx * dx + dy * dy + dz * dz) <= lim) return true;
          }
          return false;
        }
        function hideAtom(at) {
          if (!at) return;
          at.style = at.style || {};
          var kinds = ["stick", "sphere", "line", "cross", "cartoon"];
          for (var i = 0; i < kinds.length; i++) {
            var k = kinds[i];
            at.style[k] = at.style[k] || {};
            at.style[k].hidden = true;
          }
          at.clickable = false;
        }
        function showPolarHydrogen(at) {
          if (!at) return;
          at.style = at.style || {};
          at.style.cartoon = {hidden: true};
          at.style.stick = {radius: 0.08, hidden: false, color: "white"};
          at.style.sphere = {scale: 0.18, hidden: false, color: "white"};
          at.clickable = true;
        }
        function residueResKey(at) {
          return (at.chain || "") + "\t" + (at.resi == null ? "" : String(at.resi))
            + "\t" + (at.icode || "");
        }
        function atomHasAtomRepresentation(at) {
          if (!at || atomLooksHidden(at)) return false;
          var st = at.style || {};
          var kinds = ["stick", "sphere", "line", "cross"];
          for (var i = 0; i < kinds.length; i++) {
            var spec = st[kinds[i]];
            if (spec && !spec.hidden) return true;
          }
          return false;
        }
        function indexVisibleHeavyResidues(atoms) {
          var idx = {};
          for (var i = 0; i < atoms.length; i++) {
            var o = atoms[i];
            if (!o || isHydrogenAtom(o)) continue;
            if (!atomHasAtomRepresentation(o)) continue;
            idx[residueResKey(o)] = true;
          }
          return idx;
        }
        function normalizeHydrogensMode(mode) {
          if (mode === "all" || mode === "none") return mode;
          return "polar";
        }
        function applyHydrogenVisibility(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var atoms;
          try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
          if (!atoms || !atoms.length) return;
          var mode = normalizeHydrogensMode(window.molmanagerHydrogens);
          var visibleHeavies = indexVisibleHeavyResidues(atoms);
          var heavyIndex = indexResidueHeavies(atoms);
          for (var i = 0; i < atoms.length; i++) {
            var at = atoms[i];
            if (!isHydrogenAtom(at)) continue;
            if (mode === "none" || !visibleHeavies[residueResKey(at)]) {
              hideAtom(at);
              continue;
            }
            if (mode === "all") {
              showPolarHydrogen(at);
              continue;
            }
            if (hydrogenParentIsPolar(at, heavyIndex)) showPolarHydrogen(at);
            else hideAtom(at);
          }
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
          var foundPolar = false;
          if (resSels.length) {
            var resSel = resSels.length === 1 ? resSels[0] : {or: resSels};
            try {
              v.addStyle(resSel, {stick: {radius: 0.15}});
            } catch (eSt) {}
          }
          if (parts.length && normalizeHydrogensMode(window.molmanagerHydrogens) !== "none") {
            var sel = parts.length === 1 ? parts[0] : {or: parts};
            try {
              var pocketAtoms = v.selectedAtoms(sel) || [];
              var heavyIndex = indexResidueHeavies(pocketAtoms);
              for (var pi = 0; pi < pocketAtoms.length; pi++) {
                var pa = pocketAtoms[pi];
                if (!isHydrogenAtom(pa)) continue;
                if (hydrogenParentIsPolar(pa, heavyIndex)) {
                  foundPolar = true;
                  break;
                }
              }
            } catch (eHide) {}
          }
          if (!p.polarHPdb || foundPolar) return;
          if (normalizeHydrogensMode(window.molmanagerHydrogens) === "none") return;
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
            v.setStyle(
              {model: mid, elem: "D"},
              {stick: {radius: 0.08, color: "white"}, sphere: {scale: 0.18, color: "white"}}
            );
          } catch (eHmod) {}
        }
        function applyPocketSurface(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var p = window.molmanagerPocketSurface;
          if (!p || !p.active) return;
          var resSels = p.residueSels || [];
          if (!resSels.length) return;
          var sel = resSels.length === 1 ? resSels[0] : {or: resSels};
          var style = {
            opacity: (p.opacity != null) ? p.opacity : 0.7
          };
          if (p.wireframe) {
            style.wireframe = true;
            if (p.linewidth != null) style.linewidth = p.linewidth;
          }
          if (p.colorScheme === "element") {
            style.colorscheme = "default";
          } else {
            style.color = p.color || "lightgray";
          }
          var types = ($3Dmol && $3Dmol.SurfaceType) ? $3Dmol.SurfaceType : {};
          var typeKey = String(p.surfaceType || "ms").toUpperCase();
          var stype = types[typeKey] || types.MS || types.VDW;
          try {
            v.addSurface(stype, style, sel);
          } catch (eMs) {
            try { v.addSurface(types.VDW, style, sel); } catch (eVdw) {}
          }
        }
        function applyHydrogenBonds(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
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
        function applyDockingBox(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          var box = window.molmanagerDockingBox;
          if (!box || !box.active) return;
          var color = box.color || "#3D8BFF";
          var edges = box.edges || [];
          for (var i = 0; i < edges.length; i++) {
            var e = edges[i] || {};
            var start = e.start || {};
            var end = e.end || {};
            try {
              v.addLine({
                start: {x: start.x, y: start.y, z: start.z},
                end: {x: end.x, y: end.y, z: end.z},
                color: color,
                linewidth: 2
              });
            } catch (eLn) {}
          }
          var c = box.center || {};
          var s = box.size || {};
          if (c.x == null || s.x == null) return;
          try {
            v.addBox({
              corner: {
                x: c.x - s.x * 0.5,
                y: c.y - s.y * 0.5,
                z: c.z - s.z * 0.5
              },
              dimensions: {w: s.x, h: s.y, d: s.z},
              color: color,
              opacity: 0.12
            });
          } catch (eBox) {}
        }
        function removeDockPoseModel(v) {
          if (window.molmanagerDockPoseModel) {
            try { v.removeModel(window.molmanagerDockPoseModel); } catch (eRm) {}
            window.molmanagerDockPoseModel = null;
          }
        }
        function ensureDockPoseModel(v) {
          var p = window.molmanagerDockPose;
          if (!p || !p.active || !p.data) {
            removeDockPoseModel(v);
            return;
          }
          if (window.molmanagerDockPoseModel) return;
          try {
            window.molmanagerDockPoseModel = v.addModel(atob(p.data), p.fmt || "sdf");
          } catch (eAdd) {
            window.molmanagerDockPoseModel = null;
          }
        }
        function applyDockPose(v) {
          v = v || window.molmanagerViewer;
          if (!v) return;
          ensureDockPoseModel(v);
          var mdl = window.molmanagerDockPoseModel;
          if (!mdl) return;
          var mid = (mdl.id != null) ? mdl.id : null;
          if (mid == null) return;
          try {
            v.setStyle({model: mid}, {
              stick: {radius: 0.18, colorscheme: "magentaCarbon"},
              sphere: {scale: 0.26, colorscheme: "magentaCarbon"}
            });
          } catch (eSt) {}
        }
        function zoomToDockPose(v) {
          v = v || window.molmanagerViewer;
          var mdl = window.molmanagerDockPoseModel;
          if (!v || !mdl) return false;
          var mid = (mdl.id != null) ? mdl.id : null;
          if (mid == null) return false;
          try { v.resize(); } catch (e0) {}
          try { v.zoomTo({model: mid}); } catch (e1) { return false; }
          try { v.zoom(0.72); } catch (e2) {}
          v.render();
          captureHomeView(v);
          return true;
        }
        function atomLooksHidden(at) {
          if (!at) return true;
          var st = at.style;
          if (!st) return false;
          if (st.hidden) return true;
          var kinds = ["stick", "sphere", "line", "cross", "cartoon"];
          var saw = false;
          for (var i = 0; i < kinds.length; i++) {
            var spec = st[kinds[i]];
            if (!spec) continue;
            saw = true;
            if (!spec.hidden) return false;
          }
          return saw;
        }
        function ligandComponentId(atom) {
          var comps = window.molmanagerComponents || [];
          var chain = atom.chain || "";
          var resn = String(atom.resn || "").toUpperCase();
          var resi = atom.resi == null ? "" : String(atom.resi);
          for (var i = 0; i < comps.length; i++) {
            var c = comps[i];
            if (!c || c.kind !== "ligand") continue;
            if ((c.chain || "") !== chain) continue;
            if (String(c.resn || "").toUpperCase() !== resn) continue;
            if (c.resi != null && String(c.resi) !== "" && String(c.resi) !== resi) continue;
            return c.id || "";
          }
          return "";
        }
        function bindPicking(v) {
          try {
            v.setClickable({}, true, function (atom) {
              if (!atom || atomLooksHidden(atom)) return;
              var ligId = ligandComponentId(atom);
              var key = ligId
                ? ("lig:" + ligId)
                : (atom.hetflag
                  ? ["at", atom.chain || "", atom.resi == null ? "" : String(atom.resi),
                      atom.icode || "", atom.serial == null ? "" : String(atom.serial)].join("\t")
                  : ["res", atom.chain || "", atom.resi == null ? "" : String(atom.resi),
                      atom.icode || ""].join("\t"));
              var now = Date.now();
              var last = window.molmanagerLastPick || {t: 0, key: ""};
              var isDouble = (now - last.t) < 450 && last.key === key;
              window.molmanagerLastPick = {t: now, key: key};
              var payload = JSON.stringify({
                chain: atom.chain || "",
                resn: atom.resn || "",
                resi: atom.resi == null ? "" : String(atom.resi),
                icode: atom.icode || "",
                atom: atom.atom || atom.name || "",
                elem: atom.elem || "",
                serial: atom.serial == null ? "" : atom.serial,
                altLoc: atom.altLoc || atom.altloc || "",
                doubleClick: isDouble,
                model: (atom.model && typeof atom.model.id === "number")
                  ? atom.model.id
                  : (typeof atom.model === "number" ? atom.model : 0)
              });
              if (window.proteinBridge && window.proteinBridge.atomPicked) {
                window.proteinBridge.atomPicked(payload);
              }
            });
          } catch (eClick) {}
          try {
            var atoms = v.selectedAtoms({});
            for (var i = 0; i < atoms.length; i++) {
              if (atomLooksHidden(atoms[i])) atoms[i].clickable = false;
            }
            var comps = window.molmanagerComponents || [];
            for (var c = 0; c < comps.length; c++) {
              if (comps[c] && comps[c].visible) continue;
              var hiddenAtoms = v.selectedAtoms(selOf(comps[c]));
              for (var h = 0; h < hiddenAtoms.length; h++) hiddenAtoms[h].clickable = false;
            }
          } catch (eA) {}
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
        window.molmanagerPocketSurface = null;
        window.molmanagerPocketHModel = null;
        window.molmanagerHydrogens = "polar";
        window.molmanagerHbonds = null;
        window.molmanagerDockingBox = null;
        window.molmanagerDockPose = null;
        window.molmanagerDockPoseModel = null;
        installResetStructureMenu();
        connectBridge();
        bindPicking(viewer);
        window.molmanagerResizeKeepView = function () { keepViewResize(window.molmanagerViewer); };
        window.molmanagerModelCount = 0;
        function rememberPayloadOverlays(payload) {
          if (!payload) return;
          if (payload.components !== undefined) {
            window.molmanagerComponents = payload.components || [];
          }
          if (payload.fmt) window.molmanagerFmt = payload.fmt;
          if (payload.residueHighlight) {
            window.molmanagerResidueHighlight = payload.residueHighlight;
          }
          if (payload.pocket !== undefined) window.molmanagerPocket = payload.pocket || null;
          if (payload.pocketSurface !== undefined) {
            window.molmanagerPocketSurface = payload.pocketSurface || null;
          }
          if (payload.hbonds !== undefined) window.molmanagerHbonds = payload.hbonds || null;
          if (payload.dockingBox !== undefined) {
            window.molmanagerDockingBox = payload.dockingBox || null;
          }
          if (payload.dockPose !== undefined) {
            window.molmanagerDockPose = payload.dockPose || null;
          }
          if (payload.hydrogens) {
            window.molmanagerHydrogens = normalizeHydrogensMode(payload.hydrogens);
          }
        }
        function addModelsFromPayload(v, models, startIndex) {
          var added = 0;
          if (!v || !models || !models.length) return 0;
          for (var m = 0; m < models.length; m++) {
            var md = models[m] || {};
            var data = md.data || "";
            var fmt = md.fmt || window.molmanagerFmt || "pdb";
            if (!data) continue;
            try { v.addModel(atob(data), fmt); } catch (eAdd) {
              document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + eAdd + "</pre>";
              return added;
            }
            var modelId = (startIndex || 0) + added;
            if (md.cifBonds) {
              try { applyCifBondOrders(v, md.cifBonds, modelId); } catch (eBonds) {}
            }
            added++;
          }
          return added;
        }
        function finishPayloadView(v, payload) {
          applyAll(v);
          if (payload.camera) {
            try { v.setView(payload.camera); } catch (eCam) {}
            try { v.render(); } catch (eRend) {}
          } else if (payload.dockPose && payload.dockPose.active && payload.dockPose.zoom
              && zoomToDockPose(v)) {
            /* pocket zoom to the docked pose */
          } else if (payload.refit) {
            fitAndCapture(v);
          } else {
            keepViewResize(v);
          }
        }
        window.molmanagerSetProteinPayload = function (payload) {
          if (!window.molmanagerViewer || !payload) return;
          var v = window.molmanagerViewer;
          rememberPayloadOverlays(payload);
          v.clear();
          window.molmanagerModelCount = 0;
          window.molmanagerPocketHModel = null;
          window.molmanagerDockPoseModel = null;
          try { v.removeAllSurfaces(); } catch (eClr) {}
          var models = payload.models;
          if (!models || !models.length) {
            models = payload.data ? [{data: payload.data, fmt: payload.fmt || "pdb"}] : [];
          }
          window.molmanagerModelCount = addModelsFromPayload(v, models, 0);
          finishPayloadView(v, payload);
        };
        window.molmanagerAddProteinModels = function (payload) {
          if (!window.molmanagerViewer || !payload) return;
          var v = window.molmanagerViewer;
          rememberPayloadOverlays(payload);
          var start = window.molmanagerModelCount || 0;
          var n = addModelsFromPayload(v, payload.models || [], start);
          window.molmanagerModelCount = start + n;
          finishPayloadView(v, payload);
        };
        window.molmanagerGetView = function () {
          if (!window.molmanagerViewer) return null;
          try { return window.molmanagerViewer.getView(); } catch (eGet) { return null; }
        };
        window.molmanagerSetView = function (view) {
          if (!window.molmanagerViewer || view == null) return;
          try {
            window.molmanagerViewer.setView(view);
            window.molmanagerViewer.render();
          } catch (eSet) {}
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
        window.molmanagerSetPocketSurface = function (surface) {
          window.molmanagerPocketSurface = surface || null;
          if (!window.molmanagerViewer) return;
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerSetHydrogens = function (mode) {
          window.molmanagerHydrogens = normalizeHydrogensMode(mode);
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
        window.molmanagerSetDockingBox = function (box) {
          window.molmanagerDockingBox = box || null;
          if (!window.molmanagerViewer) return;
          applyAll(window.molmanagerViewer);
          keepViewResize(window.molmanagerViewer);
        };
        window.molmanagerSetDockPose = function (pose) {
          window.molmanagerDockPose = pose || null;
          var v = window.molmanagerViewer;
          if (!v) return;
          removeDockPoseModel(v);
          applyAll(v);
          if (pose && pose.active && pose.zoom && zoomToDockPose(v)) return;
          keepViewResize(v);
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
        window.molmanagerEditBond = function (payload) {
          var v = window.molmanagerViewer;
          if (!v || !payload) return;
          var selA = payload.a || {};
          var selB = payload.b || {};
          var atomsA;
          var atomsB;
          try { atomsA = v.selectedAtoms(selA); } catch (eA) { atomsA = []; }
          try { atomsB = v.selectedAtoms(selB); } catch (eB) { atomsB = []; }
          var a = atomsA && atomsA[0];
          var b = atomsB && atomsB[0];
          if (!a || !b) return;
          if (payload.action === "remove") removeBond(a, b);
          else setBond(a, b, parseInt(payload.order, 10) || 1);
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
