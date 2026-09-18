#!/usr/bin/env bash
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

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Installing Python packages from requirements.txt..."
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -e .

if [[ -f scripts/install_pytorch_pka.sh ]]; then
  echo ""
  echo "Configuring Uni-pKa PyTorch (CUDA automatically if nvidia-smi sees an NVIDIA GPU)..."
  bash scripts/install_pytorch_pka.sh --skip-requirements
fi

read -r -p "Download GNN-MTL permeability model weights? [y/N] " perm
if [[ "$perm" =~ ^[yY] ]]; then
  python scripts/bootstrap_gnn_mtl_model.py
fi

read -r -p "Download BioTransformer 3 (~120 MB JAR + knowledge base)? [y/N] " bt
if [[ "$bt" =~ ^[yY] ]]; then
  python scripts/bootstrap_biotransformer.py
fi

PLAT=linux
[[ "$(uname -s)" == "Darwin" ]] && PLAT=mac
BINDIR="$ROOT/molmanager/resources/bin/$PLAT"
echo ""
echo "Optional executables (copy into): $BINDIR"
echo "  gnina  - https://github.com/gnina/gnina (Linux binary; WSL on Windows)"
echo ""
echo "Or set MOLMANAGER_BUNDLE_DIR. Run: python -m molmanager"
