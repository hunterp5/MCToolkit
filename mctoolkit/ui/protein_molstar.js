/**
 * This file is part of mctoolkit.
 * Copyright (C) 2026 Hunter Picard
 *
 * mctoolkit is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * Qt-to-Mol* Viewer bridge: load structures/trajectories/maps, docking box,
 * pharmacophore spheres, dock pose, and molj snapshots. Inspection UI is Mol*.
 */
(function () {
  "use strict";

  var viewer = null;
  var plugin = null;
  var ready = false;
  var queue = [];
  var boxLabel = "Docking box";
  var pharmaLabel = "Pharmacophore";
  var poseLabel = "Dock pose";

  function whenReady(fn) {
    if (ready) {
      Promise.resolve(fn()).catch(function (err) {
        console.error("Mol* command failed", err);
      });
      return;
    }
    queue.push(fn);
  }

  function b64ToUint8(b64) {
    var bin = atob(b64 || "");
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function b64ToText(b64) {
    var bytes = b64ToUint8(b64);
    try {
      return new TextDecoder("utf-8").decode(bytes);
    } catch (err) {
      var s = "";
      for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
      return s;
    }
  }

  function molstarFormat(fmt) {
    var f = String(fmt || "pdb").toLowerCase();
    if (f === "cif" || f === "mmcif" || f === "mcif") return "mmcif";
    if (f === "ent" || f === "pqr") return "pdb";
    if (f === "mol" || f === "sd") return "sdf";
    return f;
  }

  function coordFmt(fmt) {
    var f = String(fmt || "dcd").toLowerCase();
    if (f === "xtc" || f === "trr" || f === "nctraj" || f === "nc") return f === "nc" ? "nctraj" : f;
    return "dcd";
  }

  function volumeName(fmt) {
    var f = String(fmt || "ccp4").toLowerCase();
    if (f === "mrc" || f === "map" || f === "ccp4") return "map." + (f === "map" ? "map" : f);
    if (f === "dsn6" || f === "brix") return "map.dsn6";
    if (f === "dx" || f === "dxbin") return "map.dx";
    if (f === "cube" || f === "cub") return "map.cube";
    return "map.ccp4";
  }

  async function clearScene() {
    if (!plugin) return;
    if (typeof plugin.clear === "function") {
      await plugin.clear();
      return;
    }
    var hier = plugin.managers && plugin.managers.structure && plugin.managers.structure.hierarchy;
    if (hier && hier.current && hier.current.structures && hier.current.structures.length) {
      await hier.remove(hier.current.structures, true);
    }
  }

  async function loadOneModel(model) {
    if (!viewer || !model || !model.data) return;
    var fmt = molstarFormat(model.fmt);
    var label = model.name || model.id || "structure";
    var text = b64ToText(model.data);
    await viewer.loadStructureFromData(text, fmt, { dataLabel: label });
  }

  async function loadStructures(payload) {
    payload = payload || {};
    var models = payload.models || [];
    if (payload.replace !== false) await clearScene();
    for (var i = 0; i < models.length; i++) await loadOneModel(models[i]);
    if (payload.refit !== false) {
      try {
        if (plugin && plugin.managers && plugin.managers.camera) {
          plugin.managers.camera.reset();
        }
      } catch (err) {}
    }
  }

  function pdbAtom(serial, name, resn, x, y, z, elem) {
    function f8(n) {
      var s = Number(n).toFixed(3);
      return ("        " + s).slice(-8);
    }
    var line =
      "HETATM" +
      ("     " + serial).slice(-5) +
      " " +
      (name + "    ").slice(0, 4) +
      " " +
      (resn + "   ").slice(0, 3) +
      " X" +
      ("    " + serial).slice(-4) +
      "    " +
      f8(x) +
      f8(y) +
      f8(z) +
      "  1.00  0.00          " +
      (elem + "  ").slice(0, 2);
    return line;
  }

  async function replaceLabeledStructure(label, pdbText) {
    if (!plugin || !viewer) return;
    var hier = plugin.managers && plugin.managers.structure && plugin.managers.structure.hierarchy;
    if (hier && hier.current && hier.current.structures) {
      var drop = hier.current.structures.filter(function (ref) {
        try {
          var cell = ref.cell || ref;
          var obj = cell.obj || {};
          var lab = String((obj.label || obj.description || "") + " " + (cell.params && cell.params.label || ""));
          return lab.indexOf(label) >= 0;
        } catch (err) {
          return false;
        }
      });
      if (drop.length && typeof hier.remove === "function") {
        try {
          await hier.remove(drop, true);
        } catch (err) {}
      }
    }
    if (pdbText) {
      await viewer.loadStructureFromData(pdbText, "pdb", { dataLabel: label });
    }
  }

  function boxPdb(spec) {
    var c = spec.center || {};
    var s = spec.size || {};
    var cx = Number(c.x || 0), cy = Number(c.y || 0), cz = Number(c.z || 0);
    var hx = Number(s.x || 0) * 0.5, hy = Number(s.y || 0) * 0.5, hz = Number(s.z || 0) * 0.5;
    var corners = [];
    var sx, sy, sz;
    for (sx = -1; sx <= 1; sx += 2) {
      for (sy = -1; sy <= 1; sy += 2) {
        for (sz = -1; sz <= 1; sz += 2) {
          corners.push([cx + sx * hx, cy + sy * hy, cz + sz * hz]);
        }
      }
    }
    var lines = ["HEADER    DOCKING BOX"];
    var i;
    for (i = 0; i < corners.length; i++) {
      var p = corners[i];
      lines.push(pdbAtom(i + 1, "C" + (i + 1), "BOX", p[0], p[1], p[2], "C"));
    }
    var pairs = [];
    for (i = 0; i < corners.length; i++) {
      var j;
      for (j = i + 1; j < corners.length; j++) {
        var d = 0;
        if (Math.abs(corners[i][0] - corners[j][0]) > 1e-6) d++;
        if (Math.abs(corners[i][1] - corners[j][1]) > 1e-6) d++;
        if (Math.abs(corners[i][2] - corners[j][2]) > 1e-6) d++;
        if (d === 1) pairs.push([i + 1, j + 1]);
      }
    }
    for (i = 0; i < pairs.length; i++) {
      lines.push(
        "CONECT" +
          ("     " + pairs[i][0]).slice(-5) +
          ("     " + pairs[i][1]).slice(-5)
      );
    }
    lines.push("END");
    return lines.join("\n");
  }

  function pharmaPdb(spec) {
    var features = spec.features || [];
    var lines = ["HEADER    PHARMACOPHORE"];
    var n = 0;
    for (var i = 0; i < features.length; i++) {
      var f = features[i] || {};
      if (f.enabled === false) continue;
      n += 1;
      var resn = String(f.type || f.atom || "PH4").slice(0, 3).toUpperCase() || "PH4";
      lines.push(
        pdbAtom(n, "X", resn, Number(f.x || 0), Number(f.y || 0), Number(f.z || 0), "He")
      );
    }
    if (!n) return "";
    lines.push("END");
    return lines.join("\n");
  }

  async function setDockingBox(spec) {
    spec = spec || {};
    if (!spec.active || !spec.center || !spec.size) {
      await replaceLabeledStructure(boxLabel, "");
      return;
    }
    await replaceLabeledStructure(boxLabel, boxPdb(spec));
  }

  async function setPharmacophore(spec) {
    spec = spec || {};
    if (!spec.active) {
      await replaceLabeledStructure(pharmaLabel, "");
      return;
    }
    var pdb = pharmaPdb(spec);
    await replaceLabeledStructure(pharmaLabel, pdb);
  }

  async function setDockPose(spec) {
    spec = spec || {};
    if (!spec.active || !spec.data) {
      await replaceLabeledStructure(poseLabel, "");
      return;
    }
    var fmt = molstarFormat(spec.fmt || "sdf");
    var text = b64ToText(spec.data);
    await replaceLabeledStructure(poseLabel, "");
    await viewer.loadStructureFromData(text, fmt, { dataLabel: poseLabel });
  }

  async function loadTrajectory(spec) {
    spec = spec || {};
    var topo = spec.topology || {};
    var coords = spec.coordinates || {};
    if (!viewer || !topo.data || !coords.data) return;
    await viewer.loadTrajectory({
      model: {
        kind: "model-data",
        data: b64ToText(topo.data),
        format: molstarFormat(topo.fmt),
      },
      coordinates: {
        kind: "coordinates-data",
        data: b64ToUint8(coords.data),
        format: coordFmt(coords.fmt),
        isBinary: true,
      },
      preset: spec.preset || "default",
    });
  }

  async function loadVolume(spec) {
    spec = spec || {};
    if (!viewer || !spec.data) return;
    var bytes = b64ToUint8(spec.data);
    var file = new File([bytes], spec.name || volumeName(spec.fmt), {
      type: "application/octet-stream",
    });
    await viewer.loadFiles([file]);
  }

  async function exportMolj() {
    if (!plugin) return null;
    try {
      if (plugin.managers && plugin.managers.snapshot && plugin.managers.snapshot.getStateSnapshot) {
        return await plugin.managers.snapshot.getStateSnapshot();
      }
    } catch (err) {}
    try {
      if (plugin.state && plugin.state.getSnapshot) return plugin.state.getSnapshot();
    } catch (err2) {}
    return null;
  }

  async function loadMolj(state) {
    if (!plugin || !state) return;
    try {
      if (plugin.managers && plugin.managers.snapshot && plugin.managers.snapshot.setStateSnapshot) {
        await plugin.managers.snapshot.setStateSnapshot(state);
        return;
      }
    } catch (err) {}
    try {
      if (plugin.state && plugin.state.setSnapshot) await plugin.state.setSnapshot(state);
    } catch (err2) {}
  }

  function resetCamera() {
    try {
      if (plugin && plugin.managers && plugin.managers.camera) plugin.managers.camera.reset();
    } catch (err) {}
  }

  function resizeViewer() {
    try {
      if (viewer && viewer.handleResize) viewer.handleResize();
    } catch (err) {}
  }

  function pickPayloadFromEvent(ev) {
    try {
      var loci = ev && ev.current && ev.current.loci;
      if (!loci) return null;
      var SP = (window.molstar && window.molstar.StructureProperties) || {};
      var SE = window.molstar && window.molstar.StructureElement;
      var loc = SE && SE.Location ? SE.Location() : null;
      if (!loc || !loci.elements || !loci.elements.length) return null;
      var el = loci.elements[0];
      var unit = el.unit;
      var indices = el.indices;
      var idx = indices && indices[0] != null ? indices[0] : 0;
      if (SE.Location.set) SE.Location.set(loc, loci.structure, unit, idx);
      else {
        loc.unit = unit;
        loc.element = idx;
      }
      var atomId = SP.atom && SP.atom.id ? SP.atom.id(loc) : idx;
      var atomName = SP.atom && SP.atom.label_atom_id ? SP.atom.label_atom_id(loc) : "";
      var authAtom = SP.atom && SP.atom.auth_atom_id ? SP.atom.auth_atom_id(loc) : atomName;
      var elem = SP.atom && SP.atom.type_symbol ? SP.atom.type_symbol(loc) : "";
      var chain = (SP.chain && (SP.chain.auth_asym_id || SP.chain.label_asym_id))
        ? (SP.chain.auth_asym_id || SP.chain.label_asym_id)(loc)
        : "";
      var resn = (SP.residue && (SP.residue.auth_comp_id || SP.residue.label_comp_id))
        ? (SP.residue.auth_comp_id || SP.residue.label_comp_id)(loc)
        : "";
      var resi = (SP.residue && (SP.residue.auth_seq_id || SP.residue.label_seq_id))
        ? (SP.residue.auth_seq_id || SP.residue.label_seq_id)(loc)
        : "";
      var icode = SP.residue && SP.residue.pdbx_PDB_ins_code ? SP.residue.pdbx_PDB_ins_code(loc) : "";
      var pos = unit && unit.conformation && unit.conformation.position
        ? unit.conformation.position(unit.elements[idx], [0, 0, 0])
        : [0, 0, 0];
      return {
        chain: chain,
        resn: resn,
        resi: resi,
        icode: icode && icode !== "?" ? icode : "",
        atom: authAtom || atomName,
        elem: elem,
        serial: atomId,
        x: pos[0],
        y: pos[1],
        z: pos[2],
        doubleClick: false,
        model: 0,
      };
    } catch (err) {
      return null;
    }
  }

  function bindPicks() {
    if (!viewer || !plugin) return;
    try {
      viewer.subscribe(plugin.behaviors.interaction.click, function (ev) {
        var payload = pickPayloadFromEvent(ev);
        if (!payload || !window.proteinBridge || !window.proteinBridge.atomPicked) return;
        window.proteinBridge.atomPicked(JSON.stringify(payload));
      });
    } catch (err) {}
  }

  function bindChannel() {
    if (typeof qt === "undefined" || !qt.webChannelTransport) return;
    new QWebChannel(qt.webChannelTransport, function (channel) {
      window.proteinBridge = channel.objects.proteinBridge;
    });
  }

  window.mctoolkitLoadStructures = function (payload) {
    whenReady(function () { return loadStructures(payload); });
  };
  window.mctoolkitClearStructures = function () {
    whenReady(function () { return clearScene(); });
  };
  window.mctoolkitSetDockingBox = function (spec) {
    whenReady(function () { return setDockingBox(spec); });
  };
  window.mctoolkitSetPharmacophore = function (spec) {
    whenReady(function () { return setPharmacophore(spec); });
  };
  window.mctoolkitSetDockPose = function (spec) {
    whenReady(function () { return setDockPose(spec); });
  };
  window.mctoolkitLoadTrajectory = function (spec) {
    whenReady(function () { return loadTrajectory(spec); });
  };
  window.mctoolkitLoadVolume = function (spec) {
    whenReady(function () { return loadVolume(spec); });
  };
  window.mctoolkitLoadMolj = function (state) {
    whenReady(function () { return loadMolj(state); });
  };
  window.mctoolkitExportMolj = function () {
    if (!ready) return null;
    return exportMolj();
  };
  window.mctoolkitResetCamera = function () {
    whenReady(function () { resetCamera(); });
  };
  window.mctoolkitResizeKeepView = function () {
    resizeViewer();
  };
  window.mctoolkitScreenshotPng = function () {
    try {
      var helper = plugin && plugin.helpers && plugin.helpers.viewportScreenshot;
      if (helper && helper.getImageDataUri) return helper.getImageDataUri();
    } catch (err) {}
    var canvas = document.querySelector("canvas");
    return canvas && canvas.toDataURL ? canvas.toDataURL("image/png") : null;
  };

  async function boot() {
    if (!window.molstar || !window.molstar.Viewer) {
      console.error("Mol* Viewer did not load");
      return;
    }
    viewer = await window.molstar.Viewer.create("app", {
      layoutIsExpanded: false,
      layoutShowControls: true,
      layoutShowRemoteState: false,
      layoutShowSequence: true,
      layoutShowLog: false,
      layoutShowLeftPanel: true,
      viewportShowExpand: true,
      viewportShowSelectionMode: true,
      viewportShowAnimation: true,
      viewportShowTrajectoryControls: true,
    });
    plugin = viewer.plugin;
    window.mctoolkitMolstarViewer = viewer;
    bindPicks();
    bindChannel();
    ready = true;
    window.mctoolkitMolstarReady = true;
    for (var i = 0; i < queue.length; i++) {
      try {
        await queue[i]();
      } catch (err) {
        console.error("Mol* queued command failed", err);
      }
    }
    queue = [];
    resizeViewer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot().catch(function (err) { console.error(err); });
    });
  } else {
    boot().catch(function (err) { console.error(err); });
  }

  window.addEventListener("resize", function () {
    resizeViewer();
  });
})();
