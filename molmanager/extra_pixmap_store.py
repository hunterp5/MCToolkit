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

"""PNG-backed extra table-column images with a decoded QPixmap LRU."""

from __future__ import annotations

from collections import OrderedDict

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
from PyQt5.QtGui import QImage, QPixmap


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
    """Holds extra-column images as PNG bytes; only a bounded LRU is decoded."""

    def __init__(self, *, max_decoded_pixmaps: int = 384) -> None:
        self._png: dict[tuple[int, str], bytes] = {}
        self._lru: OrderedDict[tuple[int, str], QPixmap] = OrderedDict()
        self._max_decoded = max(32, int(max_decoded_pixmaps))

    def clear(self) -> None:
        self._png.clear()
        self._lru.clear()

    def __len__(self) -> int:
        return len(self._png)

    def __contains__(self, key: object) -> bool:
        return key in self._png

    def pixmap(self, oid: int, header_name: str) -> QPixmap | None:
        key = (int(oid), str(header_name))
        cached = self._lru.get(key)
        if cached is not None and not cached.isNull():
            self._lru.move_to_end(key)
            return cached
        raw = self._png.get(key)
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
        raw = self._png.pop(kk, None)
        if raw is None:
            return default
        pm = QPixmap.fromImage(QImage.fromData(raw))
        return pm if pm is not None and not pm.isNull() else default

    def keys(self):
        return list(self._png)

    def items(self):
        for key in list(self._png):
            pm = self.pixmap(key[0], key[1])
            if pm is not None:
                yield key, pm

    def set_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        key = (int(oid), str(header_name))
        raw = pixmap_to_png_bytes(pixmap)
        self._lru.pop(key, None)
        if not raw:
            self._png.pop(key, None)
            return
        self._png[key] = raw

    def copy_png(self, src: tuple[int, str], dest: tuple[int, str]) -> None:
        raw = self._png.get((int(src[0]), str(src[1])))
        dest_key = (int(dest[0]), str(dest[1]))
        self._lru.pop(dest_key, None)
        if not raw:
            self._png.pop(dest_key, None)
            return
        self._png[dest_key] = raw

    def remove_oid(self, oid: int) -> None:
        oid_i = int(oid)
        for key in [k for k in self._png if k[0] == oid_i]:
            del self._png[key]
            self._lru.pop(key, None)

    def remove_header(self, header_name: str) -> None:
        header = str(header_name)
        for key in [k for k in self._png if k[1] == header]:
            del self._png[key]
            self._lru.pop(key, None)

    def keep_headers(self, headers: set[str]) -> None:
        keep = set(headers)
        for key in [k for k in self._png if k[1] not in keep]:
            del self._png[key]
            self._lru.pop(key, None)

    def rename_header(self, old: str, new: str) -> None:
        old_h, new_h = str(old), str(new)
        for oid, header in list(self._png):
            if header != old_h:
                continue
            raw = self._png.pop((oid, old_h))
            self._lru.pop((oid, old_h), None)
            self._png[(oid, new_h)] = raw
            self._lru.pop((oid, new_h), None)
