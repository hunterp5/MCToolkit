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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""RDKit physical-property calculations for a sketched molecule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, QED

from ..descriptors.medchem_descriptors import (
    ab_mps_score,
    cns_mpo_score,
    lipinski_violations,
    ro5_pass,
)
from ..ionization.unipka_ensembles import logd74_from_microstates, pka_values_from_states

_PKA_CALC_FAILED = "pKa calculation failed"


@dataclass(frozen=True)
class SketchPhysicalProperties:
    """Computed properties for one sketched (or RDKit) molecule."""

    mw: float | None = None
    tpsa: float | None = None
    logp: float | None = None
    logd: float | None = None
    pka_values: tuple[float, ...] | None = None
    pka_approx: bool = False
    ab_mps: float | None = None
    cns_mpo: float | None = None
    qed: float | None = None
    ro5_pass: str | None = None
    ro5_violations: int | None = None
    error: str | None = None


def copy_mol(mol: Chem.Mol) -> Chem.Mol:
    """Independent RDKit copy for off-thread ionization."""
    return Chem.Mol(mol)


def sanitize_copy(mol: Chem.Mol) -> Chem.Mol | None:
    try:
        out = Chem.Mol(mol)
        Chem.SanitizeMol(out)
    except Exception:
        return None
    return out


def compute_rdkit_physical_properties(mol: Chem.Mol | None) -> SketchPhysicalProperties:
    """Fast RDKit-only properties; ionization / MPO fields left empty."""
    if mol is None or mol.GetNumAtoms() == 0:
        return SketchPhysicalProperties(error="empty")
    safe = sanitize_copy(mol)
    if safe is None:
        return SketchPhysicalProperties(error="invalid")
    try:
        return SketchPhysicalProperties(
            mw=float(Descriptors.MolWt(safe)),
            tpsa=float(Descriptors.TPSA(safe)),
            logp=float(Crippen.MolLogP(safe)),
            qed=float(QED.qed(safe)),
            ro5_pass=ro5_pass(safe),
            ro5_violations=int(lipinski_violations(safe)),
        )
    except Exception as exc:
        return SketchPhysicalProperties(error=str(exc) or "invalid")


def compute_ionization_properties(
    mol: Chem.Mol,
    *,
    cancel_event: Any = None,
    states: list | None = None,
    predict_states: Callable[..., list] | None = None,
) -> dict[str, Any]:
    """Return LogD / pKa / AB-MPS / CNS MPO from a Uni-pKa ionization ensemble."""
    safe = sanitize_copy(mol)
    if safe is None:
        raise ValueError("invalid molecule")
    if states is None:
        if predict_states is None:
            raise ValueError(_PKA_CALC_FAILED)
        states = predict_states(safe, cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise ValueError("cancelled")
    if not states:
        raise ValueError(_PKA_CALC_FAILED)
    clogp = float(Crippen.MolLogP(safe))
    pkas = tuple(sorted(pka_values_from_states(states)))
    if not pkas:
        raise ValueError(_PKA_CALC_FAILED)
    logd = float(logd74_from_microstates(states, clogp))
    return {
        "logd": logd,
        "pka_values": pkas,
        "pka_approx": False,
        "ab_mps": float(ab_mps_score(safe, states)),
        "cns_mpo": float(cns_mpo_score(safe, states)),
    }


def compute_sketch_physical_properties(
    mol: Chem.Mol | None,
    *,
    with_ionization: bool = True,
    predict_states: Callable[..., list] | None = None,
) -> SketchPhysicalProperties:
    """Full property bundle for tests and one-shot callers."""
    base = compute_rdkit_physical_properties(mol)
    if base.error or base.mw is None or mol is None:
        return base
    if not with_ionization:
        return base
    try:
        ion = compute_ionization_properties(mol, predict_states=predict_states)
    except Exception as exc:
        return SketchPhysicalProperties(
            mw=base.mw,
            tpsa=base.tpsa,
            logp=base.logp,
            qed=base.qed,
            ro5_pass=base.ro5_pass,
            ro5_violations=base.ro5_violations,
            error=str(exc) or _PKA_CALC_FAILED,
        )
    return SketchPhysicalProperties(
        mw=base.mw,
        tpsa=base.tpsa,
        logp=base.logp,
        logd=float(ion["logd"]),
        pka_values=tuple(ion["pka_values"]),
        pka_approx=bool(ion["pka_approx"]),
        ab_mps=float(ion["ab_mps"]),
        cns_mpo=float(ion["cns_mpo"]),
        qed=base.qed,
        ro5_pass=base.ro5_pass,
        ro5_violations=base.ro5_violations,
    )
