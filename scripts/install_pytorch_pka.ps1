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

# Repair or install the PyTorch 2.5.1 + Uni-pKa (unipkainfer) stack in the *active* Python.
# On a fresh install, `pip install -r requirements.txt` already includes the CPU wheel.
# Run this script when pKa fails due to a conflicting torch build (e.g. after installing admet-ai).
# Pass -Cuda to replace the CPU wheel with the CUDA 12.4 build (NVIDIA GPU pKa).
param(
    [switch]$Cuda
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$stackLabel = if ($Cuda) { "CUDA 12.4 PyTorch 2.5.1" } else { "CPU PyTorch 2.5.1" }
Write-Host "Installing $stackLabel and Uni-pKa stack into:" (python -c "import sys; print(sys.executable)")
python -m pip install -U pip

Write-Host "`nRemoving ADMET-AI (requires torch>=2.8; conflicts with this torch pin)..."
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m pip uninstall -y admet-ai 2>&1 | Out-Host
$ErrorActionPreference = $prevEap

Write-Host "`nRemoving mismatched torch builds..."
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m pip uninstall -y torch torchvision torchaudio 2>&1 | Out-Host
$ErrorActionPreference = $prevEap

Write-Host "`nReinstalling dependencies from requirements.txt..."
python -m pip install -r requirements.txt
Write-Host "If pip reported dependency conflicts for molscribe/openchemie/opennmt-py, they are unrelated to Uni-pKa and can be ignored."

if ($Cuda) {
    Write-Host "`nRemoving the CPU PyTorch wheel so the CUDA build can replace it..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    python -m pip uninstall -y torch torchvision torchaudio 2>&1 | Out-Host
    $ErrorActionPreference = $prevEap
    Write-Host "`nInstalling CUDA 12.4 PyTorch 2.5.1 (this can take several minutes)..."
    python -m pip install --index-url https://download.pytorch.org/whl/cu124 --force-reinstall --no-cache-dir --no-deps torch==2.5.1 torchvision==0.20.1
}

Write-Host "`nVerifying imports..."
$env:MOLMANAGER_REQUIRE_CUDA = $(if ($Cuda) { "1" } else { "0" })
python -c @"
import os
import sys
import torch
import unipkainfer
print('OK: torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'unipkainfer', getattr(unipkainfer, '__version__', 'ok'))
if torch.cuda.is_available():
    print('GPU:', torch.cuda.get_device_name(0))
elif os.environ.get('MOLMANAGER_REQUIRE_CUDA') == '1':
    sys.exit('CUDA was requested but torch.cuda.is_available() is False. Close MolManager if it is running and retry.')
"@
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "`nDone. First pKa run downloads Uni-pKa weights (unipka-download-model). Run MolManager with this same Python."
