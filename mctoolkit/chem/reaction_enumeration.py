# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Reaction-based combinatorial enumeration (RDKit RunReactants)."""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

from ..platform_support.config import load_config
from .fragment_recomposition_filters import (
    compile_recomposition_filters,
    parse_recomposition_filter_text,
    product_passes_compiled,
)

_STRUCTURE_FILE_SUFFIXES = {".sdf", ".sd", ".smi", ".smiles", ".txt", ".csv"}


@dataclass(frozen=True)
class ReactionPreset:
    """One bundled or user-defined reaction template."""

    id: str
    name: str
    description: str
    smarts: str
    reactant_labels: tuple[str, str]


@dataclass(frozen=True)
class ReactionEnumerationRequest:
    """Inputs for one reaction-enumeration job (dialog → worker)."""

    reaction_name: str
    rxn_smarts: str
    reactant_1_mode: str
    reactant_2_mode: str
    reactant_file_1: str
    reactant_file_2: str
    reactant_smiles_1: str
    reactant_smiles_2: str
    max_products: int
    output_filters: str
    add_to_table: bool
    save_to_file: bool
    save_path: str | None


@dataclass(frozen=True)
class ReactionEnumerationJobResult:
    """Worker output consumed by the main window."""

    products: list[str]
    reaction_name: str
    skipped: int
    add_to_table: bool
    save_to_file: bool
    save_path: str | None
    written_count: int


def reaction_presets_path() -> Path:
    from ..platform_support.bundled_paths import resources_dir

    return resources_dir() / "reactions" / "presets.json"


def load_reaction_presets() -> list[ReactionPreset]:
    path = reaction_presets_path()
    if not path.is_file():
        return [_fallback_custom_preset()]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return [_fallback_custom_preset()]
    out: list[ReactionPreset] = []
    for item in raw.get("presets") or []:
        labels = list(item.get("reactant_labels") or ["Reactant 1", "Reactant 2"])
        while len(labels) < 2:
            labels.append(f"Reactant {len(labels) + 1}")
        out.append(
            ReactionPreset(
                id=str(item.get("id") or item.get("name") or "preset"),
                name=str(item.get("name") or "Reaction"),
                description=str(item.get("description") or ""),
                smarts=str(item.get("smarts") or ""),
                reactant_labels=(str(labels[0]), str(labels[1])),
            )
        )
    return out or [_fallback_custom_preset()]


def _fallback_custom_preset() -> ReactionPreset:
    return ReactionPreset(
        id="custom",
        name="Custom reaction",
        description="Enter your own two-reactant reaction SMARTS",
        smarts="",
        reactant_labels=("Reactant 1", "Reactant 2"),
    )


def validate_reaction_smarts(smarts: str) -> Chem.rdChemReactions.ChemicalReaction:
    text = (smarts or "").strip()
    if not text:
        raise ValueError("Reaction SMARTS is required.")
    rxn = AllChem.ReactionFromSmarts(text)
    if rxn is None:
        raise ValueError("Could not parse reaction SMARTS.")
    n = int(rxn.GetNumReactantTemplates())
    if n != 2:
        raise ValueError(
            f"This tool currently supports exactly two reactants (SMARTS declares {n})."
        )
    return rxn


def _mol_from_smiles_line(text: str) -> Chem.Mol | None:
    smi = (text or "").strip()
    if not smi or smi.startswith("#"):
        return None
    if "," in smi and not any(ch in smi for ch in "()[]=#@"):
        smi = smi.split(",", 1)[0].strip()
    mol = Chem.MolFromSmiles(smi)
    if mol is not None:
        return mol
    return Chem.MolFromSmiles(smi, sanitize=False)


def _load_smiles_lines(path: Path) -> list[Chem.Mol]:
    mols: list[Chem.Mol] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        mol = _mol_from_smiles_line(line)
        if mol is not None:
            mols.append(mol)
    return mols


def _load_csv_smiles(path: Path) -> list[Chem.Mol]:
    mols: list[Chem.Mol] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return mols
    header = [str(c or "").strip() for c in rows[0]]
    smi_col = next(
        (i for i, h in enumerate(header) if h and "smiles" in h.lower()),
        None,
    )
    start = 1 if smi_col is not None else 0
    if smi_col is None:
        smi_col = 0
    for row in rows[start:]:
        if smi_col >= len(row):
            continue
        mol = _mol_from_smiles_line(str(row[smi_col]))
        if mol is not None:
            mols.append(mol)
    return mols


def load_reactant_molecules_from_smiles_text(text: str) -> list[Chem.Mol]:
    """Parse reactant structures from newline-separated SMILES (or comma-separated first field)."""
    mols: list[Chem.Mol] = []
    for line in (text or "").splitlines():
        mol = _mol_from_smiles_line(line)
        if mol is not None:
            mols.append(mol)
    if not mols:
        raise ValueError("No valid SMILES were found in the reactant text.")
    return mols


def load_reactant_pool(
    *,
    source: str,
    file_path: str = "",
    smiles_text: str = "",
) -> list[Chem.Mol]:
    """Load one reactant pool from a structure file or pasted SMILES text."""
    mode = (source or "file").strip().lower()
    if mode == "smiles":
        return load_reactant_molecules_from_smiles_text(smiles_text)
    if mode == "file":
        return load_reactant_molecules(file_path)
    raise ValueError(f"Unsupported reactant input mode: {source!r}")


def load_reactant_pools(
    request: ReactionEnumerationRequest,
) -> tuple[list[Chem.Mol], list[Chem.Mol]]:
    """Load both reactant pools described by *request*."""
    return (
        load_reactant_pool(
            source=request.reactant_1_mode,
            file_path=request.reactant_file_1,
            smiles_text=request.reactant_smiles_1,
        ),
        load_reactant_pool(
            source=request.reactant_2_mode,
            file_path=request.reactant_file_2,
            smiles_text=request.reactant_smiles_2,
        ),
    )


def load_reactant_molecules(path: str | Path) -> list[Chem.Mol]:
    """Load reactant structures from SDF, SMILES text, or CSV."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"Reactant file not found: {p}")
    suffix = p.suffix.lower()
    if suffix not in _STRUCTURE_FILE_SUFFIXES:
        raise ValueError(
            f"Unsupported reactant file type {suffix!r}. Use .sdf, .smi, .smiles, .txt, or .csv."
        )
    if suffix in (".sdf", ".sd"):
        suppl = Chem.SDMolSupplier(str(p), removeHs=False)
        mols = [m for m in suppl if m is not None]
    elif suffix == ".csv":
        mols = _load_csv_smiles(p)
    else:
        mols = _load_smiles_lines(p)
    if not mols:
        raise ValueError(f"No valid structures found in {p.name}.")
    return mols


def _canonical_smiles(mol: Chem.Mol) -> str | None:
    try:
        Chem.SanitizeMol(mol)
        return Chem.MolToSmiles(mol)
    except (ValueError, RuntimeError):
        try:
            return Chem.MolToSmiles(mol, canonical=True)
        except (ValueError, RuntimeError):
            return None


def write_product_smiles_to_sdf(
    path: str | Path, smiles_list: list[str], reaction_name: str
) -> int:
    out_path = Path(path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(out_path))
    written = 0
    try:
        for i, smi in enumerate(smiles_list):
            text = (smi or "").strip()
            if not text:
                continue
            mol = Chem.MolFromSmiles(text)
            if mol is None:
                continue
            with suppress(RuntimeError, ValueError, TypeError):
                mol.SetProp("_Name", f"product_{i + 1}")
                mol.SetProp("SMILES", text)
                mol.SetProp("Reaction", reaction_name)
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    return written


def enumerate_reaction(
    rxn_smarts: str,
    reactant_pools: list[list[Chem.Mol]],
    *,
    max_products: int = 2000,
    uniquify: bool = True,
    output_filters: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> tuple[list[str], int, bool]:
    """
    Run a two-reactant reaction across the cartesian product of reactant pools.

    Returns ``(product_smiles, n_skipped_by_constraints, cancelled)``.
    """
    if cancel_event is not None and cancel_event.is_set():
        return [], 0, True
    if len(reactant_pools) != 2:
        raise ValueError("Exactly two reactant pools are required.")
    pool_a, pool_b = reactant_pools
    if not pool_a or not pool_b:
        raise ValueError("Both reactant pools must contain at least one structure.")
    rxn = validate_reaction_smarts(rxn_smarts)
    rules = parse_recomposition_filter_text(output_filters)
    compiled = compile_recomposition_filters(rules)
    cap = max(1, int(max_products))
    cfg = load_config()
    max_pairs: int | None = None
    if compiled:
        max_pairs = max(
            int(cfg.recomp_constraint_min_candidates),
            cap * int(cfg.recomp_constraint_candidate_multiplier),
        )
    seen: set[str] = set()
    products: list[str] = []
    skipped = 0
    examined = 0
    last_progress = -1

    def _report_progress() -> None:
        nonlocal last_progress
        if progress_callback is None:
            return
        accepted = len(products)
        if accepted == last_progress and examined % 32 != 0:
            return
        last_progress = accepted
        progress_callback(accepted, cap, examined)

    _report_progress()
    for mol_a in pool_a:
        for mol_b in pool_b:
            examined += 1
            if cancel_event is not None and cancel_event.is_set():
                return list(products), skipped, True
            if max_pairs is not None and examined > max_pairs:
                return list(products), skipped, False
            try:
                outcomes = rxn.RunReactants((mol_a, mol_b))
            except (RuntimeError, ValueError, TypeError):
                skipped += 1
                continue
            for outcome in outcomes:
                for pmol in outcome:
                    if pmol is None:
                        skipped += 1
                        continue
                    if compiled and not product_passes_compiled(pmol, compiled):
                        skipped += 1
                        continue
                    smi = _canonical_smiles(pmol)
                    if not smi:
                        skipped += 1
                        continue
                    if uniquify:
                        if smi in seen:
                            skipped += 1
                            continue
                        seen.add(smi)
                    products.append(smi)
                    _report_progress()
                    if len(products) >= cap:
                        return list(products), skipped, False
    return list(products), skipped, False
