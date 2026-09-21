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
"""SQL load safety helpers (no Qt)."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

# Leading statement keywords that mutate schema/data or run server-side code.
_DESTRUCTIVE_HEAD = re.compile(
    r"^\s*(?:"
    r"INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE|"
    r"GRANT|REVOKE|EXEC(?:UTE)?|CALL|ATTACH|DETACH|VACUUM|REINDEX|"
    r"COPY\s+\S+\s+FROM"
    r")\b",
    re.IGNORECASE,
)

_MULTI_STMT = re.compile(r";\s*\S", re.DOTALL)

_MUTATING_AFTER_CTE = re.compile(
    r"\)\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

_SELECT_INTO = re.compile(r"\bSELECT\b[\s\S]*\bINTO\b", re.IGNORECASE)


def _strip_sql_noise(sql: str) -> str:
    """Remove block comments and full-line ``--`` comments for heuristic checks."""
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def sql_looks_destructive(sql: str | None) -> bool:
    """Heuristic: True when ``sql`` may modify the database or run non-SELECT work."""
    text = (sql or "").strip().rstrip(";")
    if not text:
        return False
    if _MULTI_STMT.search(text):
        return True
    cleaned = _strip_sql_noise(text)
    if not cleaned:
        return False
    if _DESTRUCTIVE_HEAD.match(cleaned):
        return True
    if _MUTATING_AFTER_CTE.search(cleaned):
        return True
    if _SELECT_INTO.search(cleaned):
        return True
    return False


def is_sqlite_sqlalchemy_url(url: str) -> bool:
    return (url or "").strip().lower().startswith("sqlite")


def sqlite_database_path_from_url(url: str) -> str | None:
    """
    Extract a filesystem path from a SQLAlchemy SQLite URL.

    Returns ``None`` for in-memory or unparseable URLs.
    """
    raw = (url or "").strip()
    low = raw.lower()
    if not low.startswith("sqlite"):
        return None
    # sqlite+pysqlite:///… or sqlite:///…
    if ":///" in raw:
        path = raw.split(":///", 1)[1]
    elif "://" in raw:
        path = raw.split("://", 1)[1]
    else:
        return None
    path_only, _, _query = path.partition("?")
    if path_only.lower().startswith("file:"):
        path_only = path_only[5:]
        # file:///C:/… → /C:/… on some parsers; strip leading slash before drive.
        if len(path_only) >= 3 and path_only[0] == "/" and path_only[2] == ":":
            path_only = path_only[1:]
    path_only = path_only.strip()
    if not path_only or path_only == ":memory:":
        return None
    return path_only


def make_sqlite_read_only_creator(
    path: str, *, timeout_s: float
) -> Callable[[], sqlite3.Connection]:
    """Return a SQLAlchemy ``creator`` that opens ``path`` with SQLite ``mode=ro``."""
    resolved = Path(path).expanduser().resolve()
    uri = resolved.as_uri() + "?mode=ro"
    t_s = max(1.0, min(float(timeout_s), 300.0))

    def _creator() -> sqlite3.Connection:
        return sqlite3.connect(uri, uri=True, timeout=t_s)

    return _creator


def engine_kwargs_for_sql_load(
    url: str,
    *,
    read_only: bool,
    sqlite_timeout_s: float,
    pg_connect_timeout: int,
) -> tuple[str, dict]:
    """Build ``(url, create_engine kwargs)`` including optional SQLite read-only mode."""
    connect_args: dict = {}
    out_url = url
    eng_kw: dict = {}
    lu = url.lower().strip()
    t_s = max(1.0, min(float(sqlite_timeout_s), 300.0))

    if read_only and is_sqlite_sqlalchemy_url(url):
        path = sqlite_database_path_from_url(url)
        if path:
            # Windows-safe: Path.as_uri() + sqlite3 uri=True (SQLAlchemy file: URLs are fragile).
            eng_kw["creator"] = make_sqlite_read_only_creator(path, timeout_s=t_s)
            return "sqlite://", eng_kw

    if lu.startswith("sqlite"):
        connect_args.setdefault("timeout", t_s)
    elif "postgresql" in lu or lu.startswith("postgres"):
        connect_args["connect_timeout"] = max(1, min(int(pg_connect_timeout), 120))
    if connect_args:
        eng_kw["connect_args"] = connect_args
    return out_url, eng_kw
