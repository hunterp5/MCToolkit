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

"""One-time GUI hint when Uni-pKa could use an NVIDIA GPU but PyTorch is CPU-only."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox, QWidget

from ..ionization.unipka_ensembles import cpu_torch_with_nvidia_gpu, cuda_pka_install_hint


def maybe_remind_unipka_cuda_wheel(parent: QWidget | None) -> None:
    """Show a once-per-process dialog if nvidia-smi sees a GPU and torch is CPU-only."""
    host = parent
    if host is not None and getattr(host, "_unipka_cuda_hint_shown", False):
        return
    if not cpu_torch_with_nvidia_gpu():
        return
    if host is not None:
        host._unipka_cuda_hint_shown = True
    QMessageBox.information(parent, "Uni-pKa GPU", cuda_pka_install_hint())
