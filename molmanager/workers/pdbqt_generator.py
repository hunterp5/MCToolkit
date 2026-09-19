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

"""Generate ligand and receptor PDBQT files for docking (Meeko)."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from rdkit import Chem
from rdkit.Chem import AllChem

logger = logging.getLogger(__name__)

_MEEKO_RES_FAIL = re.compile(
    r"unable to build rdkit mol for residue \S+ corresponding to key (\S+)",
    re.I,
)
_MEEKO_KEY_HINTS = re.compile(
    r"(?:corresponding to key|inter-residue bond\(s\):|residue_key=)\s*"
    r"([A-Za-z]*:-?\d+[A-Za-z]?)",
    re.I,
)
_MEEKO_PAIR_KEYS = re.compile(r"\(([A-Za-z]*:-?\d+[A-Za-z]?),\s*([A-Za-z]*:-?\d+[A-Za-z]?)\)")
_MEEKO_SKIP_ROUNDS = 48

_MEEKO_MISSING = "Meeko is required to generate PDBQT. Install with: pip install meeko"
_GEMMI_MISSING = (
    "Meeko needs gemmi to write PDBQT (receptor Polymer templates). "
    'Install with: pip install gemmi (or pip install -e ".[docking]")'
)


def meeko_import_error(exc: BaseException) -> str:
    """Install hint when ``import meeko`` fails; Meeko often omits gemmi from pip deps."""
    name = getattr(exc, "name", None)
    text = str(exc) or ""
    if name == "gemmi" or "No module named 'gemmi'" in text or 'No module named "gemmi"' in text:
        return _GEMMI_MISSING
    if name == "meeko" or "No module named 'meeko'" in text or 'No module named "meeko"' in text:
        return _MEEKO_MISSING
    return text or _MEEKO_MISSING


@dataclass(frozen=True)
class PdbqtGenRequest:
    receptor_pdb_path: str | None
    receptor_pdbqt_out: str | None
    ligand_mode: str  # "sdf" | "pdb" | "smiles" | "rows"
    ligand_sdf_path: str | None
    ligand_smiles: list[str] | None
    ligand_rows: list[tuple[int, Chem.Mol]] | None
    ligand_pdbqt_out: str | None
    ligand_pdb_path: str | None = None
    working_dir: str | None = None


class PdbqtGenSignals(QObject):
    finished = Signal(str, str)  # receptor_pdbqt_path, ligand_pdbqt_path (empty if skipped)
    failed = Signal(str)
    logged = Signal(str)


def _read_sdf_molecules(path: Path) -> list[Chem.Mol]:
    suppl = Chem.SDMolSupplier(str(path), removeHs=False)
    return [m for m in suppl if m is not None]


_PDB_MODEL_RE = re.compile(r"^MODEL\b", re.MULTILINE)


def _split_pdb_models(text: str) -> list[str]:
    body = (text or "").replace("\r\n", "\n")
    if not body.strip():
        return []
    if _PDB_MODEL_RE.search(body):
        chunks = re.split(r"(?=^MODEL\b)", body, flags=re.MULTILINE)
        return [c.strip() + "\n" for c in chunks if c.strip()]
    return [body if body.endswith("\n") else body + "\n"]


def _mol_from_pdb_block(block: str) -> Chem.Mol | None:
    try:
        return Chem.MolFromPDBBlock(block, removeHs=False, proximityBonding=True)
    except TypeError:
        return Chem.MolFromPDBBlock(block, removeHs=False)


def _read_pdb_molecules(path: Path) -> list[Chem.Mol]:
    """Load small-molecule ligand(s) from a PDB file (one mol per MODEL, else the whole file)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    mols: list[Chem.Mol] = []
    for block in _split_pdb_models(text):
        mol = _mol_from_pdb_block(block)
        if mol is not None and mol.GetNumAtoms() > 0:
            mols.append(mol)
    if mols:
        return mols
    try:
        mol = Chem.MolFromPDBFile(str(path), removeHs=False, proximityBonding=True)
    except TypeError:
        mol = Chem.MolFromPDBFile(str(path), removeHs=False)
    if mol is None or mol.GetNumAtoms() == 0:
        return []
    return [mol]


def _embed_ligand_3d(mol: Chem.Mol) -> bool:
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
        return False
    try:
        cid = AllChem.EmbedMolecule(mol, params)
    except Exception:
        cid = -1
    if cid != 0:
        try:
            cid = AllChem.EmbedMolecule(mol, randomSeed=0xC0FFEE)
        except Exception:
            cid = -1
    if cid != 0:
        return False
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=200)
    except Exception:
        try:
            AllChem.UFFOptimizeMolecule(mol, maxIters=200)
        except Exception:
            pass
    return True


def prepare_ligand_with_hydrogens(mol: Chem.Mol) -> Chem.Mol | None:
    """
    Add explicit hydrogens to *mol* before Meeko PDBQT conversion.

    Uses existing 3D coordinates when present; otherwise embeds with ETKDG after AddHs.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
        Chem.SanitizeMol(m)
    except Exception:
        return None
    try:
        if m.GetNumConformers() > 0:
            m = Chem.AddHs(m, addCoords=True)
        else:
            m = Chem.AddHs(m)
            if not _embed_ligand_3d(m):
                return None
    except Exception:
        return None
    return m


def _prepare_ligand_mols(mols: list[Chem.Mol]) -> tuple[list[Chem.Mol], int]:
    """Return ligands with explicit H atoms; second value is the failure count."""
    prepared: list[Chem.Mol] = []
    failed = 0
    for mol in mols:
        out = prepare_ligand_with_hydrogens(mol)
        if out is None:
            failed += 1
        else:
            prepared.append(out)
    return prepared, failed


def _ligand_mols_from_request(req: PdbqtGenRequest) -> tuple[list[Chem.Mol] | None, str]:
    """Load ligand molecules from the request before hydrogen placement."""
    if req.ligand_mode == "sdf":
        if not req.ligand_sdf_path:
            return None, "Select an SDF file for ligand input."
        path = Path(req.ligand_sdf_path).expanduser()
        mols = _read_sdf_molecules(path)
        if not mols:
            return None, "Could not read any molecules from the ligand SDF file."
        return mols, ""
    if req.ligand_mode == "pdb":
        pdb_path = (req.ligand_pdb_path or "").strip()
        if not pdb_path:
            return None, "Select a PDB file for ligand input."
        path = Path(pdb_path).expanduser()
        if not path.is_file():
            return None, f"Ligand PDB file not found: {path}"
        mols = _read_pdb_molecules(path)
        if not mols:
            return None, "Could not read any molecules from the ligand PDB file."
        return mols, ""
    if req.ligand_mode == "smiles":
        smis = [s.strip() for s in (req.ligand_smiles or []) if s.strip()]
        if not smis:
            return None, "Enter at least one SMILES for ligand input."
        mols = []
        for smi in smis:
            m = Chem.MolFromSmiles(smi)
            if m is not None:
                mols.append(m)
        if not mols:
            return None, "Could not parse any provided SMILES."
        return mols, ""
    rows = list(req.ligand_rows or [])
    if not rows:
        return None, "No ligand rows were provided."
    mols = [m for _oid, m in rows if m is not None]
    if not mols:
        return None, "No valid ligands in selected rows."
    return mols, ""


def _apply_meeko_rdkit_compat() -> None:
    """
    Meeko 0.7.x still calls ``mol.HasQuery()``; RDKit 2023.09+ exposes ``HasQuery`` on atoms/bonds only.
    """
    if getattr(Chem.Mol, "_molmanager_hasquery_patched", False):
        return
    if hasattr(Chem.Mol, "HasQuery"):
        Chem.Mol._molmanager_hasquery_patched = True  # type: ignore[attr-defined]
        return

    def _mol_has_query(self: Chem.Mol) -> bool:
        return any(atom.HasQuery() for atom in self.GetAtoms()) or any(
            bond.HasQuery() for bond in self.GetBonds()
        )

    Chem.Mol.HasQuery = _mol_has_query  # type: ignore[method-assign, attr-defined]
    Chem.Mol._molmanager_hasquery_patched = True  # type: ignore[attr-defined]


def _pdb_without_hydrogens(pdb_string: str) -> str:
    """Drop explicit hydrogens so Meeko can apply residue templates."""
    lines: list[str] = []
    for line in pdb_string.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            elem = line[76:78].strip().upper() if len(line) >= 78 else ""
            name = line[12:16].strip().upper() if len(line) >= 16 else ""
            if elem in {"H", "D", "T"}:
                continue
            if not elem and (name.startswith("H") or name in {"D", "T"}):
                continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _meeko_residue_keys(*texts: str) -> list[str]:
    """Residue keys Meeko mentions in errors or warnings (``A:913``, ``:42``)."""
    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        key = key.strip().rstrip(".,;:")
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    for text in texts:
        for match in _MEEKO_KEY_HINTS.finditer(text or ""):
            _add(match.group(1))
        fail = _MEEKO_RES_FAIL.search(text or "")
        if fail:
            _add(fail.group(1))
        for match in _MEEKO_PAIR_KEYS.finditer(text or ""):
            _add(match.group(1))
            _add(match.group(2))
    return keys


def _meeko_failed_residue_key(message: str) -> str:
    keys = _meeko_residue_keys(message)
    return keys[0] if keys else ""


class _MeekoLogBuffer(logging.Handler):
    """Collect Meeko log lines so padding failures can name residues to skip."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:
            return


def _strip_pdb_residue(pdb_string: str, reskey: str) -> tuple[str, int]:
    """Remove ATOM/HETATM records for a Meeko residue key (``A:913`` or ``A:913A``)."""
    key = (reskey or "").strip()
    if ":" not in key:
        return pdb_string, 0
    chain, rest = key.split(":", 1)
    chain = (chain or " ").strip() or " "
    icode = ""
    resi = rest
    if rest and rest[-1].isalpha() and rest[:-1].lstrip("-").isdigit():
        icode = rest[-1]
        resi = rest[:-1]
    dropped = 0
    kept: list[str] = []
    for line in pdb_string.splitlines():
        if line.startswith(("ATOM", "HETATM")) and len(line) >= 26:
            f_chain = line[21:22].strip() or " "
            f_resi = line[22:26].strip()
            f_icode = line[26:27].strip() if len(line) >= 27 else ""
            if f_chain == chain and f_resi == resi and f_icode == icode:
                dropped += 1
                continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if kept else ""), dropped


def _write_receptor_pdbqt_file(pdb_path: Path, out_path: Path) -> tuple[str | None, list[str]]:
    """
    Prepare a receptor PDB with Meeko and write rigid PDBQT to *out_path*.

    Protonated hydrogens are stripped first so RDKit can build residue mols; Meeko
    templates restore hydrogens. Residues that still fail RDKit sanitize or Meeko
    padding (``unable to build rdkit mol``, excess inter-residue bonds) are
    dropped and the parse is retried. Incomplete residues are also skipped
    (Meeko ``allow_bad_res``). Runs in-process so the RDKit ``Mol.HasQuery``
    shim applies (Meeko 0.7.x / RDKit 2023.09+).

    Returns ``(error_message, ignored_residue_ids)``.
    """
    _apply_meeko_rdkit_compat()
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy, ResidueChemTemplates
        from meeko.polymer import Polymer, PolymerCreationError
    except ImportError as exc:
        return meeko_import_error(exc), []

    if not pdb_path.is_file():
        return f"Receptor PDB not found: {pdb_path}", []
    try:
        pdb_string = pdb_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read receptor PDB: {exc}", []
    pdb_string = _pdb_without_hydrogens(pdb_string)
    templates = ResidueChemTemplates.create_from_defaults()
    mk_prep = MoleculePreparation.from_config({})
    skipped: list[str] = []
    to_delete: list[str] = []
    polymer = None
    last_err = ""
    meeko_log = logging.getLogger("meeko.polymer")
    buf = _MeekoLogBuffer()
    meeko_log.addHandler(buf)
    try:
        for _round in range(_MEEKO_SKIP_ROUNDS):
            buf.messages.clear()
            try:
                polymer = Polymer.from_pdb_string(
                    pdb_string,
                    templates,
                    mk_prep,
                    residues_to_delete=list(to_delete) or None,
                    allow_bad_res=True,
                )
                last_err = ""
                break
            except Exception as exc:
                last_err = str(exc) or "Meeko receptor preparation failed."
                keys = _meeko_residue_keys(last_err, "\n".join(buf.messages))
                new_keys = [key for key in keys if key not in skipped]
                if not new_keys:
                    if not isinstance(exc, PolymerCreationError):
                        logger.exception("Meeko receptor preparation failed")
                    return last_err, skipped
                for key in new_keys:
                    pdb_string, n_drop = _strip_pdb_residue(pdb_string, key)
                    skipped.append(key)
                    if n_drop <= 0:
                        to_delete.append(key)
                    logger.info("Skipping Meeko residue %s (%s)", key, last_err)
    finally:
        meeko_log.removeHandler(buf)
    if polymer is None:
        return last_err or "Meeko could not parse the receptor PDB.", skipped
    ignored = skipped + [str(k) for k in (polymer.get_ignored_monomers() or {})]
    try:
        rigid_pdbqt, _flex = PDBQTWriterLegacy.write_from_polymer(polymer)
    except Exception as exc:
        logger.exception("Meeko PDBQT write failed")
        return str(exc) or "Meeko could not write receptor PDBQT.", ignored
    if not (rigid_pdbqt or "").strip():
        if ignored:
            listed = ", ".join(ignored)
            return f"Meeko produced an empty receptor PDBQT (ignored residues: {listed}).", ignored
        return "Meeko produced an empty receptor PDBQT.", ignored
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rigid_pdbqt, encoding="utf-8")
    return None, ignored


def _ligand_mols_for_meeko(mol: Chem.Mol) -> list[Chem.Mol]:
    """Return one single-conformer copy per 3D conformer for Meeko preparation."""
    m = Chem.Mol(mol)
    n_conf = int(m.GetNumConformers())
    if n_conf <= 1:
        return [m]
    out: list[Chem.Mol] = []
    for cid in range(n_conf):
        one = Chem.Mol(m)
        conf = Chem.Conformer(m.GetConformer(cid))
        one.RemoveAllConformers()
        one.AddConformer(conf, assignId=True)
        out.append(one)
    return out


def _write_ligand_pdbqt_file(mols: list[Chem.Mol], out_path: Path) -> str | None:
    """
    Prepare ligands with Meeko and write PDBQT to *out_path*.

    Returns an error message on failure, or ``None`` on success.
    """
    _apply_meeko_rdkit_compat()
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy
    except ImportError as exc:
        return meeko_import_error(exc)

    preparator = MoleculePreparation()
    written = 0
    errors: list[str] = []
    with out_path.open("w", encoding="utf-8") as fh:
        for index, mol in enumerate(mols, start=1):
            for lig in _ligand_mols_for_meeko(mol):
                if not lig.HasProp("_Name"):
                    lig.SetProp("_Name", f"ligand_{index}")
                try:
                    molsetups = preparator.prepare(lig)
                except Exception as exc:
                    errors.append(f"Molecule {index}: {exc}")
                    continue
                for molsetup in molsetups:
                    pdbqt_string, success, error_msg = PDBQTWriterLegacy.write_string(molsetup)
                    if not success:
                        errors.append(f"Molecule {index}: {error_msg or 'PDBQT write failed.'}")
                        continue
                    fh.write(pdbqt_string)
                    if not pdbqt_string.endswith("\n"):
                        fh.write("\n")
                    written += 1
    if written == 0:
        return "\n".join(errors) if errors else "No PDBQT models were generated."
    return None


class PdbqtGeneratorWorker(QRunnable):
    """Generate .pdbqt files using Meeko (in-process)."""

    def __init__(
        self,
        req: PdbqtGenRequest,
        *,
        signals: PdbqtGenSignals,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.req = req
        self.signals = signals
        self.cancel_event = cancel_event

    def _log(self, text: str) -> None:
        try:
            self.signals.logged.emit(text)
        except Exception:
            logger.debug("pdbqt logged emit failed", exc_info=True)

    def run(self) -> None:
        try:
            cancel_ev = self.cancel_event
            try:
                import meeko  # noqa: F401
            except ImportError as exc:
                self.signals.failed.emit(meeko_import_error(exc))
                return

            receptor_out = ""
            ligand_out = ""

            if self.req.receptor_pdb_path and self.req.receptor_pdbqt_out:
                if cancel_ev is not None and cancel_ev.is_set():
                    self.signals.failed.emit("Cancelled.")
                    return
                rec_in = Path(self.req.receptor_pdb_path).expanduser()
                rec_out = Path(self.req.receptor_pdbqt_out).expanduser()
                err, ignored = _write_receptor_pdbqt_file(rec_in, rec_out)
                if cancel_ev is not None and cancel_ev.is_set():
                    self.signals.failed.emit("Cancelled.")
                    return
                if err:
                    self.signals.failed.emit(f"Receptor PDBQT generation failed:\n{err}")
                    return
                if ignored:
                    self._log("Skipped incomplete receptor residue(s): " + ", ".join(ignored) + ".")
                receptor_out = str(rec_out)

            # Ligand
            if self.req.ligand_pdbqt_out:
                lig_out = Path(self.req.ligand_pdbqt_out).expanduser()
                lig_out.parent.mkdir(parents=True, exist_ok=True)
                source_mols, err = _ligand_mols_from_request(self.req)
                if source_mols is None:
                    self.signals.failed.emit(err)
                    return
                prepared_mols, n_failed = _prepare_ligand_mols(source_mols)
                if not prepared_mols:
                    self.signals.failed.emit(
                        "Could not add explicit hydrogens to any ligand structures."
                    )
                    return
                if n_failed:
                    self.signals.failed.emit(
                        f"Could not add explicit hydrogens to {n_failed} ligand structure(s)."
                    )
                    return
                if cancel_ev is not None and cancel_ev.is_set():
                    self.signals.failed.emit("Cancelled.")
                    return
                err = _write_ligand_pdbqt_file(prepared_mols, lig_out)
                if err:
                    self.signals.failed.emit(f"Ligand PDBQT generation failed:\n{err}")
                    return
                ligand_out = str(lig_out)

            self.signals.finished.emit(receptor_out, ligand_out)
        except Exception as e:
            self.signals.failed.emit(str(e) or "PDBQT generation failed.")
