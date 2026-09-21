/*
 * This file is part of MCToolkit.
 * Copyright (C) 2026 Hunter Picard
 *
 * MCToolkit is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * MCToolkit is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.
 */

function mctoolkitInitView() {
  try {
    __RESET_JS__
    function keepViewResize(v) {
      v = v || window.mctoolkitViewer;
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
      if (comp.selected && comp.visible && !(window.mctoolkitResidueHighlight || []).length) {
        try {
          if (style === "cartoon" || style === "surface") {
            v.addStyle(sel, {cartoon: {color: "orange"}});
          } else {
            v.addStyle(sel, {stick: {radius: 0.18, color: "orange"}});
          }
        } catch (eSel) {}
      }
    }
    function viewerSel(src) {
      var out = {};
      if (!src) return out;
      if (src.model != null && src.model !== "") out.model = src.model;
      if (src.serial != null && src.serial !== "") out.serial = src.serial;
      if (src.chain) out.chain = src.chain;
      if (src.resi != null && src.resi !== "") out.resi = src.resi;
      if (src.icode) out.icode = src.icode;
      if (src.atom) out.atom = src.atom;
      return out;
    }
    function applyResidueHighlight(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var sels = window.mctoolkitResidueHighlight || [];
      if (!sels.length) return;
      var residueParts = [];
      var atomParts = [];
      for (var i = 0; i < sels.length; i++) {
        var src = sels[i] || {};
        var asel = viewerSel(src);
        if ((src.serial != null && src.serial !== "") || src.atom) {
          atomParts.push(asel);
        } else {
          residueParts.push(asel);
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
            sphere: {scale: 0.34, color: "orange"},
            stick: {radius: 0.18, color: "orange"},
            cross: {radius: 0.7, color: "orange"}
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
    function isHydrogenAtom(at) {
      if (!at) return false;
      var raw = String(at.elem || at.element || "").replace(/[^A-Za-z]/g, "");
      if (!raw) raw = String(at.atom || at.name || "").replace(/[^A-Za-z]/g, "");
      var e = raw.toUpperCase();
      if (e === "H" || e === "D" || e === "T") return true;
      if (!e || e.charAt(0) !== "H") return false;
      var resn = String(at.resn || "").toUpperCase();
      if (e === "HE" && resn === "HE") return false;
      if (e === "HG" && resn === "HG") return false;
      if (e === "HF" || e === "HO" || e === "HS") return false;
      return e.length <= 2;
    }
    function atomIsHydrogen(at) {
      return isHydrogenAtom(at);
    }
    function atomNameLooksHydrogen(at) {
      var name = String((at && (at.atom || at.name)) || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      if (!name) return false;
      if (name === "H" || name === "D" || name === "T") return true;
      if (name.charAt(0) === "H") return name !== "HOH";
      return name.length >= 2 && name.charAt(1) === "H" && name.charAt(0) >= "0" && name.charAt(0) <= "9";
    }
    function normalizeHydrogenElements(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var atoms;
      try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
      if (!atoms || !atoms.length) return;
      for (var i = 0; i < atoms.length; i++) {
        var at = atoms[i];
        if (!at) continue;
        var resn = String(at.resn || "").toUpperCase();
        var name = String(at.atom || at.name || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
        if ((name === "HE" && resn === "HE") || (name === "HG" && resn === "HG")) continue;
        if (!isHydrogenAtom(at) && !atomNameLooksHydrogen(at)) continue;
        var raw = String(at.elem || at.element || "").replace(/[^A-Za-z]/g, "").toUpperCase();
        if (raw === "D" || raw === "T") {
          at.elem = raw;
          at.element = raw;
        } else {
          at.elem = "H";
          at.element = "H";
        }
      }
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
    function attachHydrogensToHeavies(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var atoms;
      try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
      if (!atoms || !atoms.length) return;
      var heavyIndex = indexResidueHeavies(atoms);
      var lim = 1.5 * 1.5;
      for (var j = 0; j < atoms.length; j++) {
        var at = atoms[j];
        if (!isHydrogenAtom(at)) continue;
        var bonded = false;
        var bonds = at.bonds || [];
        for (var b = 0; b < bonds.length; b++) {
          var other = bondedAtom(at, bonds[b]);
          if (other && !isHydrogenAtom(other)) {
            bonded = true;
            break;
          }
        }
        if (bonded) continue;
        var parent = null;
        var best = lim + 1;
        var heavies = heavyIndex[residueHeavyKey(at)] || [];
        for (var h = 0; h < heavies.length; h++) {
          var hv = heavies[h];
          var dx = hv.x - at.x, dy = hv.y - at.y, dz = hv.z - at.z;
          var d2 = dx * dx + dy * dy + dz * dz;
          if (d2 <= lim && d2 < best) {
            best = d2;
            parent = hv;
          }
        }
        if (parent) setBond(at, parent, 1);
      }
    }
    function applyModelStyles(v) {
      try { v.removeAllSurfaces(); } catch (eS) {}
      try { v.removeAllLabels(); } catch (eL) {}
      try { v.setStyle({}, {}); } catch (eH) {}
      try { v.removeAllShapes(); } catch (eSh) {}
      var comps = window.mctoolkitComponents || [];
      for (var i = 0; i < comps.length; i++) applyOneStyle(v, comps[i]);
      applyResidueHighlight(v);
      applyPocketOverlay(v);
      applyPocketSurface(v);
      applyDockPose(v);
    }
    function decorateAtoms(v) {
      normalizeHydrogenElements(v);
      attachHydrogensToHeavies(v);
      applyHydrogenVisibility(v);
      restylePocketHModel(v);
      applyClickTargets(v);
      bindPicking(v);
    }
    function applyShapeOverlays(v) {
      applyHydrogenBonds(v);
      applyDockingBox(v);
      applyPharmacophore(v);
    }
    function refreshShapeOverlays(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      try { v.removeAllShapes(); } catch (eSh) {}
      applyShapeOverlays(v);
      try { v.render(); } catch (eR) {}
    }
    function scheduleAtomDecorate(v) {
      window.mctoolkitDecorateGen = (window.mctoolkitDecorateGen || 0) + 1;
      var gen = window.mctoolkitDecorateGen;
      var run = function () {
        if (gen !== window.mctoolkitDecorateGen) return;
        decorateAtoms(v);
        try { v.render(); } catch (eR) {}
      };
      if (typeof requestAnimationFrame === "function") {
        requestAnimationFrame(function () { setTimeout(run, 0); });
      } else {
        setTimeout(run, 0);
      }
    }
    function applyAll(v, opts) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      opts = opts || {};
      applyModelStyles(v);
      if (!opts.deferDecorate) decorateAtoms(v);
      applyShapeOverlays(v);
      if (opts.deferDecorate) scheduleAtomDecorate(v);
    }
    function atomModelId(at) {
      if (at && at.model && typeof at.model.id === "number") return at.model.id;
      if (typeof at.model === "number") return at.model;
      return 0;
    }
    function polarHeavyAtom(at) {
      if (!at || isHydrogenAtom(at)) return false;
      return String(at.elem || "").toUpperCase() !== "C";
    }
    function polarHeavy(elem) {
      return polarHeavyAtom({elem: elem});
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
        if (other && polarHeavyAtom(other)) return true;
      }
      var list = (heavyIndex && heavyIndex[residueHeavyKey(at)]) || [];
      var lim = 1.5 * 1.5;
      for (var j = 0; j < list.length; j++) {
        var o = list[j];
        if (!polarHeavyAtom(o)) continue;
        var dx = o.x - at.x, dy = o.y - at.y, dz = o.z - at.z;
        if ((dx * dx + dy * dy + dz * dz) <= lim) return true;
      }
      return false;
    }
    function hideAtom(at) {
      if (!at) return;
      at.hidden = true;
      at.style = at.style || {};
      at.style.hidden = true;
      var kinds = ["stick", "sphere", "line", "cross", "cartoon", "clicksphere"];
      for (var i = 0; i < kinds.length; i++) {
        var k = kinds[i];
        at.style[k] = at.style[k] || {};
        at.style[k].hidden = true;
      }
      at.clickable = false;
    }
    function bondedHeavyAtom(at) {
      var bonds = (at && at.bonds) || [];
      for (var i = 0; i < bonds.length; i++) {
        var other = bondedAtom(at, bonds[i]);
        if (other && !isHydrogenAtom(other)) return other;
      }
      return null;
    }
    function showHydrogenParent(at) {
      var parent = bondedHeavyAtom(at);
      if (!parent || atomLooksHidden(parent)) return;
      parent.style = parent.style || {};
      parent.style.hidden = false;
      parent.style.stick = parent.style.stick || {};
      parent.style.stick.hidden = false;
      if (parent.style.stick.radius == null) parent.style.stick.radius = 0.12;
    }
    function showPolarHydrogen(at) {
      if (!at) return;
      at.hidden = false;
      at.style = at.style || {};
      at.style.hidden = false;
      at.style.cartoon = {hidden: true};
      at.style.stick = {radius: 0.08, hidden: false, color: "white"};
      at.style.sphere = {scale: 0.18, hidden: false, color: "white"};
      at.clickable = true;
      showHydrogenParent(at);
    }
    function residueResKey(at) {
      return atomModelId(at) + "\t" + (at.chain || "") + "\t"
        + (at.resi == null ? "" : String(at.resi)) + "\t" + (at.icode || "");
    }
    function atomHasAtomRepresentation(at) {
      if (!at || atomLooksHidden(at)) return false;
      var st = at.style || {};
      var kinds = ["stick", "sphere", "line", "cross"];
      for (var i = 0; i < kinds.length; i++) {
        var spec = st[kinds[i]];
        if (!spec || spec.hidden) continue;
        if (kinds[i] === "sphere" && spec.opacity != null && spec.opacity <= 0.05) continue;
        return true;
      }
      return false;
    }
    function indexVisibleHeavyResidues(atoms) {
      var idx = {};
      for (var i = 0; i < atoms.length; i++) {
        var o = atoms[i];
        if (!o || isHydrogenAtom(o)) continue;
        if (atomLooksHidden(o)) continue;
        if (!atomHasAtomRepresentation(o)) continue;
        idx[residueResKey(o)] = true;
      }
      return idx;
    }
    function normalizeHydrogensMode(mode) {
      if (mode === "all" || mode === "none") return mode;
      return "polar";
    }
    function applyClickTargets(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var atoms;
      try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
      if (!atoms || !atoms.length) return;
      for (var i = 0; i < atoms.length; i++) {
        var at = atoms[i];
        if (!at || atomLooksHidden(at) || (isHydrogenAtom(at) && !atomHasAtomRepresentation(at))) {
          if (at) at.clickable = false;
          continue;
        }
        at.clickable = true;
        at.style = at.style || {};
        if (at.style.sphere && at.style.sphere.opacity != null && at.style.sphere.opacity <= 0.05) {
          at.style.sphere.hidden = true;
        }
        if (atomHasAtomRepresentation(at)) continue;
        at.style.clicksphere = {hidden: false, radius: 0.8};
      }
    }
    function hydrogenHideSpec() {
      return {
        cartoon: {hidden: true},
        stick: {hidden: true},
        sphere: {hidden: true},
        line: {hidden: true},
        cross: {hidden: true},
        clicksphere: {hidden: true}
      };
    }
    function hydrogenShowSpec() {
      return {
        cartoon: {hidden: true},
        stick: {radius: 0.08, hidden: false, color: "white"},
        sphere: {scale: 0.18, hidden: false, color: "white"}
      };
    }
    function applyHydrogenSetStyle(v, sel, spec) {
      try { v.setStyle(sel, spec); } catch (eHset) {}
    }
    function applyHydrogenVisibility(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var atoms;
      try { atoms = v.selectedAtoms({}); } catch (eA) { return; }
      if (!atoms || !atoms.length) return;
      var mode = normalizeHydrogensMode(window.mctoolkitHydrogens);
      var visibleHeavies = indexVisibleHeavyResidues(atoms);
      var heavyIndex = indexResidueHeavies(atoms);
      var showByModel = {};
      for (var i = 0; i < atoms.length; i++) {
        var at = atoms[i];
        if (!isHydrogenAtom(at)) continue;
        var keep = false;
        if (mode !== "none" && visibleHeavies[residueResKey(at)]) {
          keep = (mode === "all") || hydrogenParentIsPolar(at, heavyIndex);
        }
        if (keep) {
          showPolarHydrogen(at);
          var mid = atomModelId(at);
          if (!showByModel[mid]) showByModel[mid] = [];
          showByModel[mid].push(at.serial);
        } else {
          hideAtom(at);
        }
      }
      applyHydrogenSetStyle(v, {elem: "H"}, hydrogenHideSpec());
      applyHydrogenSetStyle(v, {elem: "D"}, hydrogenHideSpec());
      applyHydrogenSetStyle(v, {elem: "T"}, hydrogenHideSpec());
      var showSpec = hydrogenShowSpec();
      for (var key in showByModel) {
        if (!Object.prototype.hasOwnProperty.call(showByModel, key)) continue;
        var serials = showByModel[key];
        if (!serials.length) continue;
        var sel = {serial: serials};
        if (key !== "") sel.model = parseInt(key, 10);
        applyHydrogenSetStyle(v, sel, showSpec);
      }
    }
    function removePocketHModel(v) {
      if (window.mctoolkitPocketHModel) {
        try { v.removeModel(window.mctoolkitPocketHModel); } catch (eRm) {}
        window.mctoolkitPocketHModel = null;
      }
    }
    function restylePocketHModel(v) {
      v = v || window.mctoolkitViewer;
      var mdl = window.mctoolkitPocketHModel;
      if (!v || !mdl) return;
      if (normalizeHydrogensMode(window.mctoolkitHydrogens) === "none") return;
      var mid = (mdl.id != null) ? mdl.id : null;
      if (mid == null) return;
      try {
        v.setStyle(
          {model: mid},
          {stick: {radius: 0.12, hidden: false}, sphere: {scale: 0.16, hidden: false}}
        );
      } catch (eRs) {}
      try {
        var atoms = v.selectedAtoms({model: mid}) || [];
        for (var i = 0; i < atoms.length; i++) {
          var at = atoms[i];
          if (!at) continue;
          at.hidden = false;
          if (isHydrogenAtom(at)) showPolarHydrogen(at);
          else {
            at.style = at.style || {};
            at.style.hidden = false;
            at.style.stick = at.style.stick || {};
            at.style.stick.hidden = false;
            if (at.style.stick.radius == null) at.style.stick.radius = 0.12;
            at.style.sphere = at.style.sphere || {};
            at.style.sphere.hidden = false;
          }
        }
      } catch (eUn) {}
    }
    function applyPocketOverlay(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      removePocketHModel(v);
      var p = window.mctoolkitPocket;
      if (!p || !p.active) return;
      var resSels = p.residueSels || [];
      var foundPolar = false;
      if (resSels.length) {
        var resSel = resSels.length === 1 ? resSels[0] : {or: resSels};
        try {
          v.addStyle(resSel, {stick: {radius: 0.15}});
        } catch (eSt) {}
        if (normalizeHydrogensMode(window.mctoolkitHydrogens) !== "none") {
          try {
            var pocketResAtoms = v.selectedAtoms(resSel) || [];
            var heavyIndex = indexResidueHeavies(pocketResAtoms);
            for (var pi = 0; pi < pocketResAtoms.length; pi++) {
              var pa = pocketResAtoms[pi];
              if (!isHydrogenAtom(pa)) continue;
              if (hydrogenParentIsPolar(pa, heavyIndex)) {
                foundPolar = true;
                break;
              }
            }
          } catch (eHide) {}
        }
      }
      if (!p.polarHPdb || foundPolar) return;
      if (normalizeHydrogensMode(window.mctoolkitHydrogens) === "none") return;
      try {
        var mdl = v.addModel(atob(p.polarHPdb), "pdb", {keepH: true});
        window.mctoolkitPocketHModel = mdl;
        var mid = (mdl && mdl.id != null) ? mdl.id : null;
        if (mid == null) {
          try { mid = v.getModel().id; } catch (eG) {}
        }
        if (mid == null) return;
        restylePocketHModel(v);
      } catch (eHmod) {}
    }
    function applyPocketSurface(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var p = window.mctoolkitPocketSurface;
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
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var spec = window.mctoolkitHbonds;
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
    function applyPharmacophore(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var spec = window.mctoolkitPharmacophore;
      if (!spec || !spec.active) return;
      var feats = spec.features || [];
      for (var i = 0; i < feats.length; i++) {
        var f = feats[i] || {};
        if (f.enabled === false) continue;
        var cx = f.x, cy = f.y, cz = f.z;
        if (cx == null || cy == null || cz == null) continue;
        var color = f.color || "#9b59b6";
        var radius = f.radius || 1.0;
        try {
          v.addSphere({
            center: {x: cx, y: cy, z: cz},
            radius: radius,
            color: color,
            alpha: 0.58
          });
          v.addSphere({
            center: {x: cx, y: cy, z: cz},
            radius: radius,
            color: color,
            alpha: 0.95,
            wireframe: true,
            linewidth: 2
          });
        } catch (eSph) {}
        var label = String(f.type || "");
        if (f.atom) label += " " + String(f.atom);
        try {
          v.addLabel(label, {
            position: {x: cx, y: cy, z: cz},
            backgroundColor: color,
            backgroundOpacity: 0.75,
            fontColor: "white",
            fontSize: 10,
            showBackground: true
          });
        } catch (eLb) {}
      }
    }
    function applyDockingBox(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      var box = window.mctoolkitDockingBox;
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
      if (window.mctoolkitDockPoseModel) {
        try { v.removeModel(window.mctoolkitDockPoseModel); } catch (eRm) {}
        window.mctoolkitDockPoseModel = null;
      }
    }
    function ensureDockPoseModel(v) {
      var p = window.mctoolkitDockPose;
      if (!p || !p.active || !p.data) {
        removeDockPoseModel(v);
        return;
      }
      if (window.mctoolkitDockPoseModel) return;
      try {
        window.mctoolkitDockPoseModel = v.addModel(atob(p.data), p.fmt || "sdf", {keepH: true});
      } catch (eAdd) {
        window.mctoolkitDockPoseModel = null;
      }
    }
    function applyDockPose(v) {
      v = v || window.mctoolkitViewer;
      if (!v) return;
      ensureDockPoseModel(v);
      var mdl = window.mctoolkitDockPoseModel;
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
      v = v || window.mctoolkitViewer;
      var mdl = window.mctoolkitDockPoseModel;
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
      if (at.hidden) return true;
      var st = at.style;
      if (!st) return false;
      if (st.hidden) return true;
      var kinds = ["stick", "sphere", "line", "cross", "cartoon", "clicksphere"];
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
      var comps = window.mctoolkitComponents || [];
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
    function bindViewerKeys() {
      if (window.mctoolkitKeysBound) return;
      window.mctoolkitKeysBound = true;
      window.addEventListener("keydown", function (ev) {
        var tag = (ev.target && ev.target.tagName) ? String(ev.target.tagName).toUpperCase() : "";
        if (tag === "INPUT" || tag === "TEXTAREA" || (ev.target && ev.target.isContentEditable)) return;
        var bridge = window.proteinBridge;
        if (!bridge) return;
        var key = ev.key;
        if (key === "Delete" || key === "Backspace") {
          ev.preventDefault();
          if (bridge.deleteRequested) bridge.deleteRequested();
          return;
        }
        var chord = ev.ctrlKey || ev.metaKey;
        if (!chord || ev.altKey) return;
        if (key === "z" || key === "Z") {
          ev.preventDefault();
          if (ev.shiftKey) {
            if (bridge.redoRequested) bridge.redoRequested();
          } else if (bridge.undoRequested) bridge.undoRequested();
        } else if (key === "y" || key === "Y") {
          ev.preventDefault();
          if (bridge.redoRequested) bridge.redoRequested();
        }
      }, true);
    }
    function bindPicking(v) {
      try {
        if (window.mctoolkitPickingBound) return;
        window.mctoolkitPickingBound = true;
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
          var last = window.mctoolkitLastPick || {t: 0, key: ""};
          var isDouble = (now - last.t) < 450 && last.key === key;
          window.mctoolkitLastPick = {t: now, key: key};
          var payload = JSON.stringify({
            chain: atom.chain || "",
            resn: atom.resn || "",
            resi: atom.resi == null ? "" : String(atom.resi),
            icode: atom.icode || "",
            atom: atom.atom || atom.name || "",
            elem: atom.elem || "",
            serial: atom.serial == null ? "" : atom.serial,
            altLoc: atom.altLoc || atom.altloc || "",
            x: atom.x,
            y: atom.y,
            z: atom.z,
            doubleClick: isDouble,
            model: (atom.model && typeof atom.model.id === "number")
              ? atom.model.id
              : (typeof atom.model === "number" ? atom.model : 0)
          });
          if (window.proteinBridge && window.proteinBridge.atomPicked) {
            window.proteinBridge.atomPicked(payload);
          }
        });
      } catch (eClick) {
        window.mctoolkitPickingBound = false;
      }
    }
    function connectBridge() {
      try {
        if (typeof QWebChannel !== "function" || typeof qt === "undefined") return;
        new QWebChannel(qt.webChannelTransport, function (channel) {
          window.proteinBridge = channel.objects.proteinBridge || null;
          bindViewerKeys();
        });
      } catch (eCh) {}
    }
    const opts = { backgroundColor: "white" };
    const viewer = $3Dmol.createViewer("v", opts);
    window.mctoolkitViewer = viewer;
    window.mctoolkitComponents = [];
    window.mctoolkitFmt = "pdb";
    window.mctoolkitResidueHighlight = [];
    window.mctoolkitPocket = null;
    window.mctoolkitPocketSurface = null;
    window.mctoolkitPocketHModel = null;
    window.mctoolkitHydrogens = "polar";
    window.mctoolkitHbonds = null;
    window.mctoolkitDockingBox = null;
    window.mctoolkitDockPose = null;
    window.mctoolkitPharmacophore = null;
    window.mctoolkitDockPoseModel = null;
    installResetStructureMenu();
    connectBridge();
    bindPicking(viewer);
    bindViewerKeys();
    window.mctoolkitResizeKeepView = function () { keepViewResize(window.mctoolkitViewer); };
    window.mctoolkitModelCount = 0;
    function rememberPayloadOverlays(payload) {
      if (!payload) return;
      if (payload.components !== undefined) {
        window.mctoolkitComponents = payload.components || [];
      }
      if (payload.fmt) window.mctoolkitFmt = payload.fmt;
      if (payload.residueHighlight) {
        window.mctoolkitResidueHighlight = payload.residueHighlight;
      }
      if (payload.pocket !== undefined) window.mctoolkitPocket = payload.pocket || null;
      if (payload.pocketSurface !== undefined) {
        window.mctoolkitPocketSurface = payload.pocketSurface || null;
      }
      if (payload.hbonds !== undefined) window.mctoolkitHbonds = payload.hbonds || null;
      if (payload.dockingBox !== undefined) {
        window.mctoolkitDockingBox = payload.dockingBox || null;
      }
      if (payload.dockPose !== undefined) {
        window.mctoolkitDockPose = payload.dockPose || null;
      }
      if (payload.pharmacophore !== undefined) {
        window.mctoolkitPharmacophore = payload.pharmacophore || null;
      }
      if (payload.hydrogens) {
        window.mctoolkitHydrogens = normalizeHydrogensMode(payload.hydrogens);
      }
    }
    function addModelsFromPayload(v, models, startIndex) {
      var added = 0;
      if (!v || !models || !models.length) return 0;
      for (var m = 0; m < models.length; m++) {
        var md = models[m] || {};
        var data = md.data || "";
        var fmt = md.fmt || window.mctoolkitFmt || "pdb";
        if (!data) continue;
        try { v.addModel(atob(data), fmt, {keepH: true}); } catch (eAdd) {
          document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + eAdd + "</pre>";
          return added;
        }
        var modelId = (startIndex || 0) + added;
        try { normalizeHydrogenElements(v); } catch (eNorm) {}
        if (md.cifBonds) {
          try { applyCifBondOrders(v, md.cifBonds, modelId); } catch (eBonds) {}
        }
        added++;
      }
      return added;
    }
    function finishPayloadView(v, payload) {
      applyAll(v, {deferDecorate: true});
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
    window.mctoolkitSetProteinPayload = function (payload) {
      if (!window.mctoolkitViewer || !payload) return;
      var v = window.mctoolkitViewer;
      rememberPayloadOverlays(payload);
      v.clear();
      window.mctoolkitModelCount = 0;
      window.mctoolkitPocketHModel = null;
      window.mctoolkitDockPoseModel = null;
      try { v.removeAllSurfaces(); } catch (eClr) {}
      var models = payload.models;
      if (!models || !models.length) {
        models = payload.data ? [{data: payload.data, fmt: payload.fmt || "pdb"}] : [];
      }
      window.mctoolkitModelCount = addModelsFromPayload(v, models, 0);
      finishPayloadView(v, payload);
    };
    window.mctoolkitAddProteinModels = function (payload) {
      if (!window.mctoolkitViewer || !payload) return;
      var v = window.mctoolkitViewer;
      rememberPayloadOverlays(payload);
      var start = window.mctoolkitModelCount || 0;
      var n = addModelsFromPayload(v, payload.models || [], start);
      window.mctoolkitModelCount = start + n;
      finishPayloadView(v, payload);
    };
    window.mctoolkitGetView = function () {
      if (!window.mctoolkitViewer) return null;
      try { return window.mctoolkitViewer.getView(); } catch (eGet) { return null; }
    };
    window.mctoolkitSetView = function (view) {
      if (!window.mctoolkitViewer || view == null) return;
      try {
        window.mctoolkitViewer.setView(view);
        window.mctoolkitViewer.render();
      } catch (eSet) {}
    };
    window.mctoolkitApplyComponentStates = function (components) {
      if (!window.mctoolkitViewer) return;
      if (components) window.mctoolkitComponents = components;
      applyAll(window.mctoolkitViewer);
      keepViewResize(window.mctoolkitViewer);
    };
    window.mctoolkitDeleteComponents = function (ids) {
      if (!window.mctoolkitViewer || !ids || !ids.length) return;
      var v = window.mctoolkitViewer;
      var model = null;
      try { model = v.getModel(); } catch (eM) {}
      var keep = [];
      var comps = window.mctoolkitComponents || [];
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
      window.mctoolkitComponents = keep;
      applyAll(v);
      keepViewResize(v);
    };
    window.mctoolkitSetResidueHighlight = function (sels) {
      window.mctoolkitResidueHighlight = sels || [];
      applyAll(window.mctoolkitViewer);
      keepViewResize(window.mctoolkitViewer);
    };
    window.mctoolkitSetPocket = function (pocket) {
      window.mctoolkitPocket = pocket || null;
      if (!window.mctoolkitViewer) return;
      applyAll(window.mctoolkitViewer);
      keepViewResize(window.mctoolkitViewer);
    };
    window.mctoolkitSetPocketSurface = function (surface) {
      window.mctoolkitPocketSurface = surface || null;
      if (!window.mctoolkitViewer) return;
      applyAll(window.mctoolkitViewer);
      keepViewResize(window.mctoolkitViewer);
    };
    window.mctoolkitSetHydrogens = function (mode) {
      window.mctoolkitHydrogens = normalizeHydrogensMode(mode);
      if (!window.mctoolkitViewer) return;
      applyAll(window.mctoolkitViewer);
      keepViewResize(window.mctoolkitViewer);
    };
    window.mctoolkitSetHbonds = function (spec) {
      window.mctoolkitHbonds = spec || null;
      if (!window.mctoolkitViewer) return;
      refreshShapeOverlays(window.mctoolkitViewer);
    };
    window.mctoolkitSetDockingBox = function (box) {
      window.mctoolkitDockingBox = box || null;
      if (!window.mctoolkitViewer) return;
      refreshShapeOverlays(window.mctoolkitViewer);
    };
    window.mctoolkitSetDockPose = function (pose) {
      window.mctoolkitDockPose = pose || null;
      var v = window.mctoolkitViewer;
      if (!v) return;
      removeDockPoseModel(v);
      applyAll(v);
      if (pose && pose.active && pose.zoom && zoomToDockPose(v)) return;
      keepViewResize(v);
    };
    window.mctoolkitSetPharmacophore = function (spec) {
      window.mctoolkitPharmacophore = spec || null;
      if (!window.mctoolkitViewer) return;
      refreshShapeOverlays(window.mctoolkitViewer);
    };
    window.mctoolkitMutateResidues = function (items) {
      var v = window.mctoolkitViewer;
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
    window.mctoolkitDeleteResidues = function (sels) {
      var v = window.mctoolkitViewer;
      if (!v || !sels || !sels.length) return;
      var model = null;
      try { model = v.getModel(); } catch (eM) {}
      for (var i = 0; i < sels.length; i++) {
        try {
          var atoms = v.selectedAtoms(viewerSel(sels[i]));
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
    window.mctoolkitEditBond = function (payload) {
      var v = window.mctoolkitViewer;
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
    window.mctoolkitZoomToComponents = function (ids) {
      var v = window.mctoolkitViewer;
      if (!v) return;
      var comps = window.mctoolkitComponents || [];
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
    window.mctoolkitZoomToSelections = function (sels) {
      var v = window.mctoolkitViewer;
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
      if (window.mctoolkitResizeKeepView) window.mctoolkitResizeKeepView();
    });
  } catch (e) {
    document.body.innerHTML = "<pre style='padding:12px;font-family:monospace'>3Dmol error: " + e + "</pre>";
  }
}
