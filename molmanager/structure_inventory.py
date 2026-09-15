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


"""Inventory polymer chains, ligands, metals, and solvent from structure files."""

from __future__ import annotations


from collections import defaultdict
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from .structure_cif import (
    _cif_cell,
    _cif_col,
    _cif_loop_index,
    _cif_missing,
    _cif_yes,
    _parse_cif_loops,
)
from .structure_component_types import (
    AA_ONE_TO_THREE,
    AA_THREE_TO_ONE,
    AMINO_ACIDS,
    CHAIN_COLORS,
    LoadedStructure,
    METAL_ELEMENTS,
    METAL_RESIDUES,
    NUCLEIC_ACIDS,
    NUCLEIC_THREE_TO_ONE,
    PolymerChain,
    PolymerResidue,
    SEQ_LETTER_LIGAND,
    SEQ_LETTER_METAL,
    SEQ_LETTER_OTHER,
    SEQ_LETTER_WATER,
    SEQUENCE_ALPHABET,
    STRUCTURE_FORMAT_BY_SUFFIX,
    SequenceEdit,
    StructureComponent,
    WATER_RESIDUES,
    _REMARK_465_ROW,
    _ResidueBucket,
    _norm_chain,
    _resi_selection_value,
)


def sniff_structure_format(path: str | Path, text: str) -> str:
    """Return a 3Dmol-oriented format id from suffix and contents."""
    suffix = Path(path).suffix.lower()
    if suffix in STRUCTURE_FORMAT_BY_SUFFIX:
        return STRUCTURE_FORMAT_BY_SUFFIX[suffix]
    stripped = (text or "").lstrip()
    if stripped.startswith("data_"):
        return "cif"
    head = stripped[:80].upper()
    if head.startswith(
        ("ATOM", "HETATM", "HEADER", "TITLE", "REMARK", "MODEL", "CRYST1", "COMPND")
    ):
        return "pdb"
    if "ROOT" in stripped[:400] or "TORSDOF" in stripped[:800]:
        return "pdbqt"
    return "pdb"


def viewer_format_for(sniffed: str) -> str:
    """3Dmol ``addModel`` format string for a sniffed file type."""
    if sniffed in {"pdbqt", "pdb", "pqr", "ent"}:
        return "pdb" if sniffed != "pqr" else "pqr"
    if sniffed in {"cif", "mmcif"}:
        return "cif"
    return sniffed


def parse_structure_components(text: str, fmt: str) -> tuple[StructureComponent, ...]:
    """Build Manager rows from PDB-like or mmCIF atom records."""
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        residues = _residues_from_cif(text)
    else:
        residues = _residues_from_pdb(text)
    return _components_from_residues(residues)


def scope_structure_component(
    spec: StructureComponent, *, structure_id: str, model: int
) -> StructureComponent:
    """Prefix *spec* so it is unique in a multi-file viewer session."""
    sel = dict(spec.selection or {})
    sel["model"] = int(model)
    cid = spec.component_id
    prefix = f"{structure_id}:"
    if not cid.startswith(prefix):
        cid = prefix + cid
    return replace(spec, component_id=cid, structure_id=structure_id, selection=sel)


def load_structure_file(path: str | Path) -> LoadedStructure:
    """Read a crystallographic file and inventory its chains / heteros."""
    rec = Path(str(path)).expanduser()
    raw_bytes = rec.read_bytes()
    if b"\x00" in raw_bytes[:4096]:
        raise ValueError(f"{rec.name} looks binary; use PDB, mmCIF, PDBQT, or another text format.")
    text = raw_bytes.decode("utf-8", errors="replace")
    sniffed = sniff_structure_format(rec, text)
    parse_fmt = "cif" if sniffed == "cif" else "pdb"
    components = parse_structure_components(text, parse_fmt)
    return LoadedStructure(
        path=rec,
        text=text,
        sniffed_format=sniffed,
        viewer_format=viewer_format_for(sniffed),
        components=components,
    )


def component_id_for_atom(
    components: Iterable[StructureComponent],
    *,
    chain: str,
    resn: str,
    resi: str | int | None,
    icode: str = "",
    model: int | None = None,
    structure_id: str = "",
) -> str | None:
    """Map a clicked 3Dmol atom onto the most specific Manager row."""
    chain_s = _norm_chain(chain)
    resn_s = (resn or "").strip().upper()
    resi_s = str(resi).strip() if resi is not None else ""
    icode_s = (icode or "").strip()
    items = list(components)
    if model is not None:
        scoped = [
            c
            for c in items
            if (c.selection or {}).get("model") == model
            or (c.selection or {}).get("model") == int(model)
        ]
        if scoped:
            items = scoped
    if structure_id:
        scoped = [c for c in items if c.structure_id == structure_id]
        if scoped:
            items = scoped
    for kind in ("water", "ligand", "metal", "other"):
        for comp in items:
            if comp.kind != kind:
                continue
            if kind == "water":
                if resn_s not in WATER_RESIDUES:
                    continue
                if comp.chain and _norm_chain(comp.chain) != chain_s:
                    continue
                return comp.component_id
            if _norm_chain(comp.chain) != chain_s:
                continue
            if comp.resn.upper() != resn_s:
                continue
            if comp.resi and comp.resi != resi_s:
                continue
            if comp.icode and comp.icode != icode_s:
                continue
            return comp.component_id
    for comp in items:
        if comp.kind == "polymer" and _norm_chain(comp.chain) == chain_s:
            return comp.component_id
    if items:
        return items[0].component_id
    return None


def _residues_from_pdb(text: str) -> list[_ResidueBucket]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    saw_model = False
    for line in (text or "").splitlines():
        rec = line[:6].strip().upper() if line else ""
        if rec == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if rec == "ENDMDL" and buckets:
            break
        if rec not in {"ATOM", "HETATM"}:
            continue
        padded = line.ljust(80)
        name = padded[12:16].strip()
        resn = padded[17:20].strip() or name[:3]
        chain = _norm_chain(padded[21:22])
        resi = padded[22:26].strip() or "0"
        icode = padded[26:27].strip()
        elem = padded[76:78].strip() or "".join(ch for ch in name if ch.isalpha())[:2]
        het = rec == "HETATM"
        key = (chain, resn.upper(), resi, icode)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _ResidueBucket(chain=chain, resn=resn.upper(), resi=resi, icode=icode, het=het)
            buckets[key] = bucket
        bucket.n_atoms += 1
        bucket.elements.add(elem.upper())
        bucket.het = bucket.het or het
    return list(buckets.values())


def _residues_from_cif(text: str) -> list[_ResidueBucket]:
    buckets: dict[tuple[str, str, str, str], _ResidueBucket] = {}
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_atom_site.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_group = _cif_col(index, "group_PDB")
        i_symbol = _cif_col(index, "type_symbol")
        i_comp = _cif_col(index, "auth_comp_id", "label_comp_id")
        i_asym = _cif_col(index, "auth_asym_id", "label_asym_id")
        i_seq = _cif_col(index, "auth_seq_id", "label_seq_id")
        i_icode = _cif_col(index, "pdbx_PDB_ins_code")
        i_model = _cif_col(index, "pdbx_PDB_model_num")
        first_model = ""
        for row in rows:
            if i_model is not None:
                model = _cif_cell(row, i_model, "1") or "1"
                if not first_model:
                    first_model = model
                elif model != first_model:
                    continue
            group = _cif_cell(row, i_group, "ATOM")
            resn = _cif_cell(row, i_comp, "UNK").upper() or "UNK"
            chain_raw = _cif_cell(row, i_asym, "?") or "?"
            resi = _cif_cell(row, i_seq, "0") or "0"
            icode = _cif_cell(row, i_icode)
            elem = _cif_cell(row, i_symbol)
            chain = _norm_chain(chain_raw)
            het = str(group).upper().startswith("HET")
            key = (chain, resn, str(resi), icode)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = _ResidueBucket(
                    chain=chain, resn=resn, resi=str(resi), icode=icode, het=het
                )
                buckets[key] = bucket
            bucket.n_atoms += 1
            bucket.elements.add(elem.upper())
            bucket.het = bucket.het or het
    return list(buckets.values())


def _classify_residue(bucket: _ResidueBucket) -> str:
    resn = bucket.resn.upper()
    if resn in WATER_RESIDUES:
        return "water"
    if resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS:
        return "polymer"
    if resn in METAL_RESIDUES:
        return "metal"
    elems = {el.upper() for el in bucket.elements if el}
    if bucket.n_atoms <= 2 and elems and elems <= METAL_ELEMENTS:
        return "metal"
    if bucket.n_atoms == 1 and elems <= ({"CL", "BR", "F", "I"} | METAL_ELEMENTS):
        return "metal"
    if bucket.het:
        return "ligand"
    return "polymer"


def _residue_selection(bucket: _ResidueBucket) -> dict[str, Any]:
    sel: dict[str, Any] = {
        "chain": bucket.chain,
        "resn": bucket.resn,
        "resi": _resi_selection_value(bucket.resi),
    }
    if bucket.icode:
        sel["icode"] = bucket.icode
    if bucket.het:
        sel["hetflag"] = True
    return sel


def _not_or(parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not parts:
        return None
    if len(parts) == 1:
        return {"not": parts[0]}
    return {"not": {"or": parts}}


def _and(parts: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned = [p for p in parts if p]
    if not cleaned:
        return {}
    if len(cleaned) == 1:
        return cleaned[0]
    return {"and": cleaned}


def _whole_structure_component(*, n_atoms: int = 0, n_residues: int = 0) -> StructureComponent:
    return StructureComponent(
        component_id="structure",
        kind="other",
        label="Structure",
        chain="",
        resn="",
        resi="",
        icode="",
        n_atoms=n_atoms,
        n_residues=n_residues,
        color="#7f8c8d",
        default_style="stick",
        default_visible=True,
        selection={},
    )


def _components_from_residues(residues: list[_ResidueBucket]) -> tuple[StructureComponent, ...]:
    if not residues:
        return (_whole_structure_component(),)
    classified = [(bucket, _classify_residue(bucket)) for bucket in residues]
    by_kind: dict[str, list[_ResidueBucket]] = defaultdict(list)
    for bucket, kind in classified:
        by_kind[kind].append(bucket)

    chain_ids = sorted({bucket.chain for bucket, _kind in classified}, key=_chain_sort_key)
    chain_color = {chain: CHAIN_COLORS[i % len(CHAIN_COLORS)] for i, chain in enumerate(chain_ids)}
    water_resns = sorted({b.resn for b in by_kind.get("water", [])})

    out: list[StructureComponent] = []
    ligand_color_i = 0
    for chain in chain_ids:
        polymer_res = [b for b in by_kind.get("polymer", []) if b.chain == chain]
        if polymer_res:
            exclude: list[dict[str, Any]] = [{"resn": resn} for resn in water_resns]
            for kind in ("ligand", "metal", "other"):
                for bucket in by_kind.get(kind, []):
                    if bucket.chain != chain:
                        continue
                    exclude.append(_residue_selection(bucket))
            sel = _and([{"chain": chain}, _not_or(exclude) or {}])
            out.append(
                StructureComponent(
                    component_id=f"polymer:{chain}",
                    kind="polymer",
                    label="Polymer",
                    chain=chain,
                    resn="",
                    resi="",
                    icode="",
                    n_atoms=sum(b.n_atoms for b in polymer_res),
                    n_residues=len(polymer_res),
                    color=chain_color[chain],
                    default_style="cartoon",
                    default_visible=True,
                    selection=sel,
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("ligand", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            color = CHAIN_COLORS[(ligand_color_i + 4) % len(CHAIN_COLORS)]
            ligand_color_i += 1
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"ligand:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="ligand",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color=color,
                    default_style="ballstick",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("metal", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"metal:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="metal",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color="#f1c40f",
                    default_style="sphere",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

        waters = [b for b in by_kind.get("water", []) if b.chain == chain]
        if waters:
            chain_water_resns = sorted({b.resn for b in waters})
            if len(chain_water_resns) == 1:
                resn_sel: dict[str, Any] = {"resn": chain_water_resns[0]}
            else:
                resn_sel = {"or": [{"resn": r} for r in chain_water_resns]}
            out.append(
                StructureComponent(
                    component_id=f"water:{chain}",
                    kind="water",
                    label="Water",
                    chain=chain,
                    resn=chain_water_resns[0] if len(chain_water_resns) == 1 else "",
                    resi="",
                    icode="",
                    n_atoms=sum(b.n_atoms for b in waters),
                    n_residues=len(waters),
                    color="#e74c3c",
                    default_style="sphere",
                    default_visible=False,
                    selection=_and([{"chain": chain}, resn_sel]),
                )
            )

        for bucket in sorted(
            [b for b in by_kind.get("other", []) if b.chain == chain],
            key=lambda b: (b.resn, _resi_sort(b.resi), b.icode),
        ):
            resi_lab = bucket.resi + bucket.icode
            out.append(
                StructureComponent(
                    component_id=f"other:{bucket.chain}:{bucket.resn}:{resi_lab}",
                    kind="other",
                    label=f"{bucket.resn} {resi_lab}",
                    chain=bucket.chain,
                    resn=bucket.resn,
                    resi=bucket.resi,
                    icode=bucket.icode,
                    n_atoms=bucket.n_atoms,
                    n_residues=1,
                    color="#7f8c8d",
                    default_style="stick",
                    default_visible=True,
                    selection=_residue_selection(bucket),
                )
            )

    if not out:
        n_atoms = sum(b.n_atoms for b in residues)
        out.append(_whole_structure_component(n_atoms=n_atoms, n_residues=len(residues)))
    return tuple(out)


def _chain_sort_key(chain: str) -> tuple[int, str]:
    return (0 if len(chain) == 1 and chain.isalpha() else 1, chain)


def _resi_sort(resi: str) -> tuple[int, str]:
    try:
        return (int(resi), resi)
    except (TypeError, ValueError):
        return (10**9, resi)


def amino_acid_letter(resn: str) -> str:
    """One-letter code for a residue name; unknown amino acids become X."""
    return AA_THREE_TO_ONE.get((resn or "").strip().upper(), "X")


def sequence_letter_for(resn: str, kind: str) -> str:
    """Sequence-window character for a residue of the given Manager kind."""
    if kind == "water":
        return SEQ_LETTER_WATER
    if kind == "metal":
        return SEQ_LETTER_METAL
    if kind == "ligand":
        return SEQ_LETTER_LIGAND
    if kind == "other":
        return SEQ_LETTER_OTHER
    key = (resn or "").strip().upper()
    if key in NUCLEIC_THREE_TO_ONE:
        letter = NUCLEIC_THREE_TO_ONE[key]
    elif key in AA_THREE_TO_ONE:
        letter = AA_THREE_TO_ONE[key]
    elif kind in {"polymer", "missing"}:
        letter = amino_acid_letter(key)
    else:
        return SEQ_LETTER_OTHER
    return letter.lower() if kind == "missing" else letter


def letter_to_resn(letter: str) -> str | None:
    """Canonical PDB residue name for a 1-letter code, or None if invalid."""
    key = (letter or "").strip().upper()
    return AA_ONE_TO_THREE.get(key)


def _norm_seq_resi(resi: str) -> str:
    raw = str(resi or "").strip() or "0"
    try:
        return str(int(raw))
    except ValueError:
        return raw


def polymer_sequence_entries(
    text: str, fmt: str
) -> dict[str, tuple[tuple[str, str, str, bool], ...]]:
    """SEQRES / mmCIF polymer residues: ``chain → ((resn, resi, icode, present), ...)``.

    ``present`` is False when coordinates are missing (REMARK 465 or ``pdb_mon_id`` ``?``).
    """
    fmt_l = (fmt or "pdb").lower()
    if fmt_l in {"cif", "mmcif"}:
        entries = _polymer_seq_from_cif(text)
    else:
        entries = _polymer_seq_from_pdb(text)
    return {chain: tuple(rows) for chain, rows in entries.items() if rows}


def _polymer_seq_from_cif(text: str) -> dict[str, list[tuple[str, str, str, bool]]]:
    out: dict[str, list[tuple[str, str, str, bool]]] = defaultdict(list)
    for tags, rows in _parse_cif_loops(text):
        if not any(t.lower().startswith("_pdbx_poly_seq_scheme.") for t in tags):
            continue
        index = _cif_loop_index(tags)
        i_strand = _cif_col(index, "pdb_strand_id", "asym_id")
        i_resn = _cif_col(index, "mon_id", "auth_mon_id", "pdb_mon_id")
        i_seq = _cif_col(index, "auth_seq_num", "pdb_seq_num", "ndb_seq_num")
        i_auth_seq = _cif_col(index, "auth_seq_num")
        i_pdb_seq = _cif_col(index, "pdb_seq_num")
        i_observed = _cif_col(index, "pdb_mon_id", "auth_mon_id")
        i_icode = _cif_col(index, "pdb_ins_code")
        i_het = _cif_col(index, "hetero")
        if i_strand is None or i_resn is None:
            continue
        for row in rows:
            if _cif_yes(_cif_cell(row, i_het)):
                continue
            resn = _cif_cell(row, i_resn).upper()
            if not resn:
                continue
            chain = _norm_chain(_cif_cell(row, i_strand, "?") or "?")
            observed_name = _cif_cell(row, i_observed) if i_observed is not None else resn
            present = not _cif_missing(observed_name)
            seq_raw = ""
            if present and i_auth_seq is not None:
                seq_raw = _cif_cell(row, i_auth_seq)
            if _cif_missing(seq_raw) and i_pdb_seq is not None:
                seq_raw = _cif_cell(row, i_pdb_seq)
            if _cif_missing(seq_raw) and i_seq is not None:
                seq_raw = _cif_cell(row, i_seq)
            resi = _norm_seq_resi(seq_raw)
            icode = _cif_cell(row, i_icode)
            if _cif_missing(icode):
                icode = ""
            out[chain].append((resn, resi, icode, present))
    return dict(out)


def _pdb_seqres_names(text: str) -> dict[str, list[str]]:
    names: dict[str, list[str]] = defaultdict(list)
    for line in (text or "").splitlines():
        if not line.upper().startswith("SEQRES"):
            continue
        padded = line.ljust(80)
        chain = _norm_chain(padded[11:12])
        names[chain].extend(tok.upper() for tok in padded[19:].split() if tok)
    return dict(names)


def _pdb_remark_465(text: str) -> dict[str, list[tuple[str, str, str]]]:
    missing: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for line in (text or "").splitlines():
        if not line.upper().startswith("REMARK 465"):
            continue
        padded = line.ljust(80)
        header = padded[10:].strip().upper()
        if not header or header.startswith(
            ("MISSING", "THE FOLLOWING", "EXPERIMENT", "M RES", "IDENT", "SSSEQ")
        ):
            continue
        resn = padded[15:18].strip().upper()
        chain = _norm_chain(padded[19:20])
        resi = padded[21:26].strip()
        icode = padded[26:27].strip()
        if not resn or not resi:
            match = _REMARK_465_ROW.match(line.strip())
            if match is None:
                continue
            resn, chain, resi, icode = (
                match.group(1).upper(),
                match.group(2),
                match.group(3),
                match.group(4) or "",
            )
            chain = _norm_chain(chain)
        missing[chain].append((resn, _norm_seq_resi(resi), icode))
    return dict(missing)


def _polymer_seq_from_pdb(text: str) -> dict[str, list[tuple[str, str, str, bool]]]:
    observed: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for bucket in _residues_from_pdb(text):
        if _classify_residue(bucket) != "polymer":
            continue
        observed[bucket.chain][(_norm_seq_resi(bucket.resi), bucket.icode)] = bucket.resn
    missing = _pdb_remark_465(text)
    seqres = _pdb_seqres_names(text)
    chains = sorted({*observed, *missing, *seqres}, key=_chain_sort_key)
    out: dict[str, list[tuple[str, str, str, bool]]] = {}
    for chain in chains:
        by_key: dict[tuple[str, str], tuple[str, bool]] = {}
        for (resi, icode), resn in observed.get(chain, {}).items():
            by_key[(resi, icode)] = (resn, True)
        for resn, resi, icode in missing.get(chain, []):
            key = (resi, icode)
            if key not in by_key:
                by_key[key] = (resn, False)
        if not by_key:
            continue
        ordered_keys = sorted(by_key, key=lambda item: (_resi_sort(item[0]), item[1]))
        names = seqres.get(chain) or []
        if names and len(names) == len(ordered_keys):
            out[chain] = [
                (names[i], resi, icode, by_key[(resi, icode)][1])
                for i, (resi, icode) in enumerate(ordered_keys)
            ]
        else:
            out[chain] = [(by_key[key][0], key[0], key[1], by_key[key][1]) for key in ordered_keys]
    return out


def parse_polymer_sequences(text: str, fmt: str) -> tuple[PolymerChain, ...]:
    """Return ordered sequences per chain ID, including missing SEQRES residues."""
    fmt_l = (fmt or "pdb").lower()
    buckets = _residues_from_cif(text) if fmt_l in {"cif", "mmcif"} else _residues_from_pdb(text)
    seq_entries = polymer_sequence_entries(text, fmt)
    by_chain: dict[str, list[PolymerResidue]] = defaultdict(list)
    seq_keys: set[tuple[str, str, str]] = set()
    for chain, entries in seq_entries.items():
        for resn, resi, icode, present in entries:
            seq_keys.add((chain, resi, icode))
            kind = "polymer" if present else "missing"
            by_chain[chain].append(
                PolymerResidue(
                    chain=chain,
                    resn=resn,
                    resi=resi,
                    icode=icode,
                    letter=sequence_letter_for(resn, kind),
                    kind=kind,
                )
            )
    for bucket in buckets:
        kind = _classify_residue(bucket)
        resi = _norm_seq_resi(bucket.resi)
        key = (bucket.chain, resi, bucket.icode)
        if kind == "polymer" and key in seq_keys:
            continue
        by_chain[bucket.chain].append(
            PolymerResidue(
                chain=bucket.chain,
                resn=bucket.resn,
                resi=resi,
                icode=bucket.icode,
                letter=sequence_letter_for(bucket.resn, kind),
                kind=kind,
            )
        )
    chains: list[PolymerChain] = []
    for chain_id in sorted(by_chain, key=_chain_sort_key):
        ordered = sorted(
            by_chain[chain_id],
            key=lambda res: (_resi_sort(res.resi), res.icode, res.resn, res.kind),
        )
        if ordered:
            chains.append(PolymerChain(chain=chain_id, residues=ordered))
    return tuple(chains)


def polymer_residue_for_atom(
    chains: Iterable[PolymerChain],
    *,
    chain: str,
    resi: str | int | None,
    icode: str = "",
    structure_id: str = "",
) -> PolymerResidue | None:
    """Match a clicked atom to a polymer residue."""
    chain_s = _norm_chain(chain)
    resi_s = str(resi).strip() if resi is not None else ""
    icode_s = (icode or "").strip()
    for poly in chains:
        if structure_id and poly.structure_id and poly.structure_id != structure_id:
            continue
        if _norm_chain(poly.chain) != chain_s:
            continue
        for res in poly.residues:
            if (res.icode or "") != icode_s:
                continue
            if res.resi == resi_s or _norm_seq_resi(res.resi) == _norm_seq_resi(resi_s):
                return res
    return None


def diff_sequence_edit(old: str, new: str) -> SequenceEdit:
    """Describe mutations and deletions needed to go from *old* to *new* 1-letter strings."""
    old_s = old or ""
    new_s = new or ""
    if any(ch not in SEQUENCE_ALPHABET for ch in new_s):
        return SequenceEdit((), (), rejected_insert=False, invalid_letter=True)
    if new_s == old_s:
        return SequenceEdit((), (), rejected_insert=False, invalid_letter=False)
    mutations: list[tuple[int, str]] = []
    deletions: list[int] = []
    rejected_insert = False
    matcher = SequenceMatcher(a=old_s, b=new_s, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            rejected_insert = True
            continue
        if tag == "delete":
            deletions.extend(range(i1, i2))
            continue
        old_len = i2 - i1
        new_len = j2 - j1
        shared = min(old_len, new_len)
        for offset in range(shared):
            if old_s[i1 + offset] != new_s[j1 + offset]:
                mutations.append((i1 + offset, new_s[j1 + offset]))
        if new_len > old_len:
            rejected_insert = True
        elif old_len > new_len:
            deletions.extend(range(i1 + shared, i2))
    return SequenceEdit(
        mutations=tuple(mutations),
        deletions=tuple(sorted(set(deletions))),
        rejected_insert=rejected_insert,
        invalid_letter=False,
    )


def _pdb_residue_key(line: str) -> tuple[str, str, str] | None:
    rec = line[:6].strip().upper() if line else ""
    if rec not in {"ATOM", "HETATM"}:
        return None
    padded = line.ljust(80)
    chain = _norm_chain(padded[21:22])
    resi = padded[22:26].strip() or "0"
    icode = padded[26:27].strip()
    return (chain, resi, icode)


def rewrite_pdb_residue_names(text: str, changes: list[tuple[str, str, str, str]]) -> str:
    """Set PDB residue names for ``(chain, resi, icode, new_resn)`` records."""
    by_key = {
        (chain, resi, icode): (new_resn or "UNK").strip().upper()[:3].ljust(3)
        for chain, resi, icode, new_resn in changes
    }
    if not by_key:
        return text
    out: list[str] = []
    for line in (text or "").splitlines():
        key = _pdb_residue_key(line)
        if key is not None and key in by_key:
            padded = line.ljust(80)
            line = f"{padded[:17]}{by_key[key]}{padded[20:]}"
        out.append(line.rstrip())
    return "\n".join(out) + ("\n" if out else "")


def delete_pdb_residues(text: str, keys: set[tuple[str, str, str]]) -> str:
    """Drop ATOM/HETATM records whose ``(chain, resi, icode)`` is in *keys*."""
    if not keys:
        return text
    out: list[str] = []
    for line in (text or "").splitlines():
        key = _pdb_residue_key(line)
        if key is not None and key in keys:
            continue
        out.append(line.rstrip())
    return "\n".join(out) + ("\n" if out else "")
