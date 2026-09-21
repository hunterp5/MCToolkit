# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""One-time GUI hint when Uni-pKa could use an NVIDIA GPU but PyTorch is CPU-only."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from ..ionization.unipka_ensembles import cpu_torch_with_nvidia_gpu, cuda_pka_install_hint


class _CudaHintRelay(QObject):
    """Marshal GPU-hint results onto the GUI thread."""

    checked = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.checked.connect(self._on_checked, Qt.QueuedConnection)

    def _on_checked(self, parent: object, needed: bool) -> None:
        host = parent if isinstance(parent, QWidget) else None
        if host is not None:
            host._unipka_cuda_hint_pending = False
            if getattr(host, "_unipka_cuda_hint_shown", False):
                return
        if not needed:
            return
        if host is not None:
            host._unipka_cuda_hint_shown = True
        QMessageBox.information(host, "Uni-pKa GPU", cuda_pka_install_hint())


_RELAY: _CudaHintRelay | None = None
_RELAY_LOCK = threading.Lock()


def _relay() -> _CudaHintRelay:
    global _RELAY
    with _RELAY_LOCK:
        if _RELAY is None:
            _RELAY = _CudaHintRelay()
        return _RELAY


def maybe_remind_unipka_cuda_wheel(parent: QWidget | None) -> None:
    """Show a once-per-process dialog if nvidia-smi sees a GPU and torch is CPU-only.

    The check runs on a daemon thread so Predict pKa / Protonate / Generate
    Protomers can open without stalling Qt on ``nvidia-smi`` (or a torch import
    in older detection paths).
    """
    host = parent
    if host is None:
        return
    if getattr(host, "_unipka_cuda_hint_shown", False):
        return
    if getattr(host, "_unipka_cuda_hint_pending", False):
        return
    host._unipka_cuda_hint_pending = True
    relay = _relay()

    def _check() -> None:
        needed = bool(cpu_torch_with_nvidia_gpu())
        relay.checked.emit(host, needed)

    threading.Thread(target=_check, daemon=True, name="unipka-cuda-hint").start()
