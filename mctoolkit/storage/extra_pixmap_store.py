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

"""PNG-backed extra table-column images with a decoded QPixmap LRU."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPixmap

from .temp_sqlite import close_owned_sqlite, open_owned_sqlite


def pixmap_to_png_bytes(pixmap: QPixmap | None) -> bytes | None:
    """Encode *pixmap* as PNG bytes, or ``None`` when the image is empty."""
    if pixmap is None or pixmap.isNull():
        return None
    ba = QByteArray()
    buf = QBuffer(ba)
    if not buf.open(QIODevice.WriteOnly):
        return None
    ok = pixmap.save(buf, "PNG")
    buf.close()
    if not ok:
        return None
    raw = bytes(ba)
    return raw or None


class ExtraPixmapStore:
    """Holds extra-column images as PNG bytes on disk; only a bounded LRU is decoded."""

    def __init__(
        self,
        *,
        max_decoded_pixmaps: int = 384,
        db_path: str | Path | None = None,
    ) -> None:
        self._owns_path = db_path is None
        if db_path is None:
            self._path, self._conn = open_owned_sqlite("mctoolkit_xpix_")
        else:
            import sqlite3

            self._path = Path(db_path)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS images ("
            "oid INTEGER NOT NULL, header TEXT NOT NULL, blob BLOB NOT NULL, "
            "PRIMARY KEY (oid, header))"
        )
        self._conn.commit()
        self._lru: OrderedDict[tuple[int, str], QPixmap] = OrderedDict()
        self._max_decoded = max(32, int(max_decoded_pixmaps))
        self._count = self._count_rows()
        self._closed = False

    def _count_rows(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM images").fetchone()
        return int(row[0] if row else 0)

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._lru.clear()
        close_owned_sqlite(self._path, self._conn, owns_path=self._owns_path)
        self._count = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def clear(self) -> None:
        self._conn.execute("DELETE FROM images")
        self._conn.commit()
        self._lru.clear()
        self._count = 0

    def __len__(self) -> int:
        return int(self._count)

    def __contains__(self, key: object) -> bool:
        parsed = self._parse_key(key)
        if parsed is None:
            return False
        oid, header = parsed
        if (oid, header) in self._lru:
            return True
        row = self._conn.execute(
            "SELECT 1 FROM images WHERE oid = ? AND header = ? LIMIT 1",
            (oid, header),
        ).fetchone()
        return row is not None

    @staticmethod
    def _parse_key(key: object) -> tuple[int, str] | None:
        if not isinstance(key, tuple) or len(key) != 2:
            return None
        try:
            return int(key[0]), str(key[1])
        except (TypeError, ValueError):
            return None

    def _raw(self, oid: int, header: str) -> bytes | None:
        row = self._conn.execute(
            "SELECT blob FROM images WHERE oid = ? AND header = ?",
            (oid, header),
        ).fetchone()
        if row is None or not row[0]:
            return None
        return bytes(row[0])

    def pixmap(self, oid: int, header_name: str) -> QPixmap | None:
        key = (int(oid), str(header_name))
        cached = self._lru.get(key)
        if cached is not None and not cached.isNull():
            self._lru.move_to_end(key)
            return cached
        raw = self._raw(*key)
        if not raw:
            return None
        pm = QPixmap.fromImage(QImage.fromData(raw))
        if pm.isNull():
            return None
        self._lru[key] = pm
        self._lru.move_to_end(key)
        while len(self._lru) > self._max_decoded:
            self._lru.popitem(last=False)
        return pm

    def get(self, key: tuple[int, str], default=None):
        oid, header = key
        pm = self.pixmap(int(oid), str(header))
        return default if pm is None else pm

    def __setitem__(self, key: tuple[int, str], pixmap: QPixmap | None) -> None:
        self.set_pixmap(int(key[0]), str(key[1]), pixmap)

    def pop(self, key: tuple[int, str], default=None):
        oid_i, header = int(key[0]), str(key[1])
        kk = (oid_i, header)
        self._lru.pop(kk, None)
        raw = self._raw(oid_i, header)
        cur = self._conn.execute("DELETE FROM images WHERE oid = ? AND header = ?", (oid_i, header))
        self._conn.commit()
        if cur.rowcount > 0:
            self._count = max(0, self._count - 1)
        if raw is None:
            return default
        pm = QPixmap.fromImage(QImage.fromData(raw))
        return pm if pm is not None and not pm.isNull() else default

    def pixmaps_for_oid(self, oid: int) -> dict[str, QPixmap]:
        oid_i = int(oid)
        out: dict[str, QPixmap] = {}
        for (header,) in self._conn.execute("SELECT header FROM images WHERE oid = ?", (oid_i,)):
            pm = self.pixmap(oid_i, str(header))
            if pm is not None and not pm.isNull():
                out[str(header)] = QPixmap(pm)
        return out

    def pixmaps_for_header(self, header_name: str) -> dict[int, QPixmap]:
        header = str(header_name)
        out: dict[int, QPixmap] = {}
        for (oid,) in self._conn.execute("SELECT oid FROM images WHERE header = ?", (header,)):
            pm = self.pixmap(int(oid), header)
            if pm is not None and not pm.isNull():
                out[int(oid)] = QPixmap(pm)
        return out

    def keys(self):
        return [
            (int(oid), str(header))
            for oid, header in self._conn.execute("SELECT oid, header FROM images")
        ]

    def items(self):
        for key in self.keys():
            pm = self.pixmap(key[0], key[1])
            if pm is not None:
                yield key, pm

    def set_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        key = (int(oid), str(header_name))
        raw = pixmap_to_png_bytes(pixmap)
        self._lru.pop(key, None)
        existed = self._conn.execute(
            "SELECT 1 FROM images WHERE oid = ? AND header = ? LIMIT 1",
            key,
        ).fetchone()
        if not raw:
            if existed is not None:
                self._conn.execute("DELETE FROM images WHERE oid = ? AND header = ?", key)
                self._conn.commit()
                self._count = max(0, self._count - 1)
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO images (oid, header, blob) VALUES (?, ?, ?)",
            (key[0], key[1], raw),
        )
        self._conn.commit()
        if existed is None:
            self._count += 1

    def copy_png(self, src: tuple[int, str], dest: tuple[int, str]) -> None:
        raw = self._raw(int(src[0]), str(src[1]))
        dest_key = (int(dest[0]), str(dest[1]))
        self._lru.pop(dest_key, None)
        existed = self._conn.execute(
            "SELECT 1 FROM images WHERE oid = ? AND header = ? LIMIT 1",
            dest_key,
        ).fetchone()
        if not raw:
            if existed is not None:
                self._conn.execute("DELETE FROM images WHERE oid = ? AND header = ?", dest_key)
                self._conn.commit()
                self._count = max(0, self._count - 1)
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO images (oid, header, blob) VALUES (?, ?, ?)",
            (dest_key[0], dest_key[1], raw),
        )
        self._conn.commit()
        if existed is None:
            self._count += 1

    def remove_oid(self, oid: int) -> None:
        oid_i = int(oid)
        cur = self._conn.execute("DELETE FROM images WHERE oid = ?", (oid_i,))
        self._conn.commit()
        dropped = max(0, int(cur.rowcount or 0))
        self._count = max(0, self._count - dropped)
        for key in [k for k in self._lru if k[0] == oid_i]:
            self._lru.pop(key, None)

    def remove_header(self, header_name: str) -> None:
        header = str(header_name)
        cur = self._conn.execute("DELETE FROM images WHERE header = ?", (header,))
        self._conn.commit()
        dropped = max(0, int(cur.rowcount or 0))
        self._count = max(0, self._count - dropped)
        for key in [k for k in self._lru if k[1] == header]:
            self._lru.pop(key, None)

    def keep_headers(self, headers: set[str]) -> None:
        keep = set(headers)
        current = {str(h) for (h,) in self._conn.execute("SELECT DISTINCT header FROM images")}
        for header in current - keep:
            self.remove_header(header)

    def rename_header(self, old: str, new: str) -> None:
        old_h, new_h = str(old), str(new)
        rows = self._conn.execute(
            "SELECT oid, blob FROM images WHERE header = ?", (old_h,)
        ).fetchall()
        if not rows:
            return
        self._conn.execute("DELETE FROM images WHERE header = ?", (old_h,))
        self._conn.executemany(
            "INSERT OR REPLACE INTO images (oid, header, blob) VALUES (?, ?, ?)",
            [(int(oid), new_h, blob) for oid, blob in rows],
        )
        self._conn.commit()
        for oid, _blob in rows:
            self._lru.pop((int(oid), old_h), None)
            self._lru.pop((int(oid), new_h), None)
        self._count = self._count_rows()
