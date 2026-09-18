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

# Install molmanager Python dependencies and show where to place optional CLI binaries.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Installing Python packages from requirements.txt..."
python -m pip install -U pip
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pip install -e .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (Test-Path "scripts\install_pytorch_pka.ps1") {
    Write-Host ""
    Write-Host "Configuring Uni-pKa PyTorch (CUDA automatically if nvidia-smi sees an NVIDIA GPU)..."
    & "scripts\install_pytorch_pka.ps1" -SkipRequirements
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$perm = Read-Host "Download GNN-MTL permeability model weights? [y/N]"
if ($perm -match '^[yY]') {
    python scripts/bootstrap_gnn_mtl_model.py
}

$bt = Read-Host "Download BioTransformer 3 (~120 MB JAR + knowledge base)? [y/N]"
if ($bt -match '^[yY]') {
    python scripts/bootstrap_biotransformer.py
}

$binDir = Join-Path $Root "molmanager\resources\bin\win"
Write-Host ""
Write-Host "Optional executables (copy into):"
Write-Host "  $binDir"
Write-Host "    gnina  - Linux binary from https://github.com/gnina/gnina (run via WSL on Windows)"
Write-Host ""
Write-Host "Or set MOLMANAGER_BUNDLE_DIR to a folder containing those binaries."
Write-Host "Run: python -m molmanager"
