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

"""Encode/decode MolManager ``.cms`` session documents (compact v2 + gzip)."""

from __future__ import annotations

import gzip
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SESSION_FORMAT = "molmanager_session"
SESSION_FORMAT_ALIASES = frozenset(
    {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
)
SESSION_VERSION_CURRENT = 2
SESSION_VERSIONS_SUPPORTED = frozenset({1, 2})

_GZIP_MAGIC = b"\x1f\x8b"

# Top-level keys that may be dropped when empty to shrink saved documents.
_OMIT_IF_EMPTY = frozenset(
    {
        "zoomed_ids",
        "structure_field_override",
        "workspace_layout",
        "docked_plots",
        "floating_plots",
        "table_layout",
        "filters",
        "column_logical_order",
        "sort_column",
        "sort_mode",
        "column_colors",
        "logarithmic_columns",
        "confs_sidecar",
        "som_browse",
        "ionization_sidecar",
        "mmp_ledger",
    }
)


def session_format_ok(fmt: object) -> bool:
    return isinstance(fmt, str) and fmt in SESSION_FORMAT_ALIASES


def session_version_ok(version: object) -> bool:
    try:
        return int(version) in SESSION_VERSIONS_SUPPORTED
    except (TypeError, ValueError):
        return False


def _dumps_json_bytes(obj: Any) -> bytes:
    try:
        import orjson

        return orjson.dumps(obj)
    except Exception:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _loads_json_bytes(raw: bytes) -> Any:
    try:
        import orjson

        return orjson.loads(raw)
    except Exception:
        return json.loads(raw.decode("utf-8"))


def dumps_session_document(doc: dict[str, Any], *, gzip_compress: bool = True) -> bytes:
    """Serialize a session document to bytes (gzip by default)."""
    payload = _dumps_json_bytes(doc)
    if not gzip_compress:
        return payload
    return gzip.compress(payload, compresslevel=6)


def loads_session_bytes(raw: bytes | str) -> dict[str, Any]:
    """Parse session file bytes (gzip or plain JSON) into a dict."""
    if isinstance(raw, str):
        data = raw.encode("utf-8")
    else:
        data = raw
    if data.startswith(_GZIP_MAGIC):
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise ValueError(f"Could not decompress session file: {exc}") from exc
    doc = _loads_json_bytes(data)
    if not isinstance(doc, dict):
        raise ValueError("Session root must be a JSON object.")
    return doc


def _is_empty_optional(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def compact_session_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert an internal (v1-shaped) document to compact session version 2."""
    headers = list(doc.get("headers") or [])
    data_headers = [h for h in headers if h and h not in ("ID_HIDDEN", "Structure")]
    rows = doc.get("rows") or []
    ids: list[int] = []
    values: list[list[str]] = []
    if isinstance(rows, list):
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            try:
                oid = int(entry["id"])
            except (KeyError, TypeError, ValueError):
                continue
            cells = entry.get("cells") or {}
            if not isinstance(cells, dict):
                cells = {}
            ids.append(oid)
            values.append([str(cells.get(h, "") or "") for h in data_headers])

    out: dict[str, Any] = {
        "format": doc.get("format") or SESSION_FORMAT,
        "version": SESSION_VERSION_CURRENT,
        "headers": headers,
        "data_headers": data_headers,
        "ids": ids,
        "values": values,
        "next_oid": int(doc.get("next_oid", 0) or 0),
        "filter_panel_visible": bool(doc.get("filter_panel_visible", False)),
        "plot_panel_visible": bool(doc.get("plot_panel_visible", True)),
        "plot_panel_width": doc.get("plot_panel_width"),
        "sort_ascending": bool(doc.get("sort_ascending", True)),
    }
    for key, value in doc.items():
        if key in out or key in ("rows", "version", "data_headers", "ids", "values"):
            continue
        if key in _OMIT_IF_EMPTY and _is_empty_optional(value):
            continue
        out[key] = value
    # Drop empties that we always copy above when unused.
    for key in list(out.keys()):
        if key in _OMIT_IF_EMPTY and _is_empty_optional(out[key]):
            del out[key]
    if out.get("plot_panel_width") is None:
        out.pop("plot_panel_width", None)
    return out


def expand_session_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize v1/v2 documents to the internal shape used by session restore."""
    if not isinstance(doc, dict):
        raise ValueError("Session root must be a JSON object.")
    version = int(doc.get("version", 0) or 0)
    if version == 1 or ("rows" in doc and "ids" not in doc):
        out = dict(doc)
        out.setdefault("version", 1)
        return out
    if version != 2 and "ids" not in doc:
        raise ValueError(f"Unsupported session version: {version}")

    headers = list(doc.get("headers") or [])
    data_headers = list(doc.get("data_headers") or [])
    if not data_headers:
        data_headers = [h for h in headers if h and h not in ("ID_HIDDEN", "Structure")]
    ids = list(doc.get("ids") or [])
    values = list(doc.get("values") or [])
    rows: list[dict[str, Any]] = []
    n = min(len(ids), len(values))
    for i in range(n):
        try:
            oid = int(ids[i])
        except (TypeError, ValueError):
            continue
        row_vals = values[i]
        if not isinstance(row_vals, (list, tuple)):
            continue
        cells: dict[str, str] = {}
        for j, h in enumerate(data_headers):
            if j < len(row_vals):
                cells[str(h)] = str(row_vals[j] if row_vals[j] is not None else "")
            else:
                cells[str(h)] = ""
        rows.append({"id": oid, "cells": cells})

    out = dict(doc)
    out["version"] = 2
    out["rows"] = rows
    # Keep columnar keys out of restore workers that only need rows.
    out.pop("ids", None)
    out.pop("values", None)
    out.pop("data_headers", None)
    return out
