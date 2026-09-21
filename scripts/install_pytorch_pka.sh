#!/usr/bin/env bash
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit.  If not, see <https://www.gnu.org/licenses/>.

# Repair or install the PyTorch 2.5.1 + Uni-pKa (unipkainfer) stack in the active Python.
# On a fresh install, `pip install -r requirements.txt` already includes the CPU wheel.
# Run this script when pKa fails due to a conflicting torch build (e.g. after installing admet-ai).
# With no flags, an NVIDIA GPU (nvidia-smi) selects the CUDA 12.4 wheel automatically.
# Pass --cuda to force CUDA, or --cpu to keep the CPU wheel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CUDA=0
CPU=0
SKIP_REQUIREMENTS=0
for arg in "$@"; do
  case "$arg" in
    --cuda) CUDA=1 ;;
    --cpu) CPU=1 ;;
    --skip-requirements) SKIP_REQUIREMENTS=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done
if [[ "$CUDA" -eq 1 && "$CPU" -eq 1 ]]; then
  echo "Use only one of --cuda or --cpu." >&2
  exit 1
fi

nvidia_gpu_present() {
  command -v nvidia-smi >/dev/null 2>&1 || return 1
  local out
  out="$(nvidia-smi -L 2>/dev/null || true)"
  [[ "$out" == *GPU* ]]
}

if [[ "$CPU" -eq 1 ]]; then
  CUDA=0
elif [[ "$CUDA" -eq 0 ]]; then
  if nvidia_gpu_present; then
    CUDA=1
    echo "NVIDIA GPU detected; installing CUDA 12.4 PyTorch (~2.5 GB). Pass --cpu to keep the CPU wheel."
  else
    echo "No NVIDIA GPU detected; installing CPU PyTorch. Pass --cuda to force the CUDA wheel."
  fi
fi

if [[ "$CUDA" -eq 1 ]]; then
  echo "Installing CUDA 12.4 PyTorch 2.5.1 and Uni-pKa stack into: $(python -c 'import sys; print(sys.executable)')"
else
  echo "Installing CPU PyTorch 2.5.1 and Uni-pKa stack into: $(python -c 'import sys; print(sys.executable)')"
fi
python -m pip install -U pip

echo
echo "Removing ADMET-AI (requires torch>=2.8; conflicts with this torch pin)..."
python -m pip uninstall -y admet-ai 2>/dev/null || true

if [[ "$SKIP_REQUIREMENTS" -eq 0 ]]; then
  echo
  echo "Removing mismatched torch builds..."
  python -m pip uninstall -y torch torchvision torchaudio 2>/dev/null || true

  echo
  echo "Reinstalling dependencies from requirements.txt..."
  python -m pip install -r requirements.txt
  echo "If pip reported dependency conflicts for molscribe/openchemie/opennmt-py, they are unrelated to Uni-pKa and can be ignored."
fi

if [[ "$CUDA" -eq 1 ]]; then
  echo
  echo "Removing the CPU PyTorch wheel so the CUDA build can replace it..."
  python -m pip uninstall -y torch torchvision torchaudio 2>/dev/null || true
  echo
  echo "Installing CUDA 12.4 PyTorch 2.5.1 (this can take several minutes)..."
  python -m pip install --index-url https://download.pytorch.org/whl/cu124 --force-reinstall --no-cache-dir --no-deps torch==2.5.1 torchvision==0.20.1
fi

echo
echo "Verifying imports..."
python -c "
import sys
import torch
import unipkainfer
print('OK: torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'unipkainfer', getattr(unipkainfer, '__version__', 'ok'))
print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')
if ${CUDA} == 1 and not torch.cuda.is_available():
    sys.exit('CUDA was requested but torch.cuda.is_available() is False.')
"

echo
echo "Done. First pKa run downloads Uni-pKa weights (unipka-download-model). Use this same Python for python -m mctoolkit."
