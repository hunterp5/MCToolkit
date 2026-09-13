# MolManager

MolManager is a desktop application for working with chemical structures in a spreadsheet-style table. You can open SDF, SMILES, and CSV files; draw structures; calculate descriptors; cluster compounds; dock ligands; and more. It is built with **Python**, **PyQt5**, and **RDKit**.

This guide walks you through installation from scratch. It assumes you are new to Python and the command line. Follow the steps in order for your operating system.

---

## What you will need

| Requirement | Details |
|-------------|---------|
| **Computer** | Windows 10 or later, macOS 10.15+, or a recent Linux distribution |
| **Internet** | Required to download Python, MolManager, and dependencies |
| **Disk space** | About 1–2 GB for a basic install; more if you add optional machine-learning tools (pKa prediction, permeability models) |
| **Python** | Version **3.10** or **3.11** (3.11 is recommended). Python 3.12+ may work but is less tested |

You do **not** need to know how to program. You will copy and paste a few commands into a terminal window.

---

## Part 1 — Install Python

Python is the language MolManager is written in. You need it installed before anything else.

### Windows

1. Open your web browser and go to [https://www.python.org/downloads/](https://www.python.org/downloads/).
2. Click the yellow **Download Python 3.11.x** button (or the latest 3.11 release).
3. Run the installer.
4. **Important:** On the first screen, check the box that says **“Add python.exe to PATH”** at the bottom. If you skip this, the steps below will not work.
5. Click **Install Now** and wait for it to finish.

**Check that Python installed correctly**

1. Press the **Windows key**, type **PowerShell**, and open **Windows PowerShell**.
2. Type this and press **Enter**:

   ```powershell
   python --version
   ```

   You should see something like `Python 3.11.9`. If you see an error, close PowerShell, reinstall Python, and make sure **Add to PATH** was checked.

### macOS

1. Open **Terminal** (search for it in Spotlight).
2. Check whether Python is already installed:

   ```bash
   python3 --version
   ```

3. If you see `Python 3.10` or `3.11`, you can continue. If not, install Python from [python.org/downloads](https://www.python.org/downloads/) or with Homebrew:

   ```bash
   brew install python@3.11
   ```

### Linux

Most distributions include Python 3. Install it with your package manager if needed, for example:

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install python3 python3-venv python3-pip

# Fedora
sudo dnf install python3 python3-pip
```

Verify:

```bash
python3 --version
```

---

## Part 2 — Download MolManager

You need a copy of the MolManager project on your computer.

### Option A — Download as a ZIP (simplest)

1. Go to the MolManager repository on GitHub.
2. Click the green **Code** button, then **Download ZIP**.
3. Extract the ZIP to a folder you will remember, for example:
   - Windows: `C:\Users\YourName\Documents\MolManager`
   - macOS/Linux: `~/Documents/MolManager`

### Option B — Clone with Git (if you use Git)

```bash
git clone https://github.com/hunterp5/MolManager.git
cd MolManager
```

All remaining steps assume your terminal is **inside the MolManager folder** (the folder that contains `README.md`, `requirements.txt`, and the `molmanager` subfolder).

**Windows — open a terminal in that folder**

1. Open File Explorer and navigate to the MolManager folder.
2. Click the address bar, type `powershell`, and press **Enter**.

   A PowerShell window opens already pointed at the right folder.

**macOS / Linux**

```bash
cd ~/Documents/MolManager
```

(replace the path with wherever you extracted or cloned the project)

---

## Part 3 — What is a virtual environment?

Before installing MolManager, you will create a **Python virtual environment** (often called a **venv**).

Think of it as a private toolbox for this one application:

- All of MolManager’s dependencies are installed **inside** that toolbox.
- They do not mix with other Python programs on your computer.
- You can delete the toolbox (the `.venv` folder) without affecting anything else.

You will create the venv once, activate it whenever you work with MolManager, and install packages into it. The folder is named `.venv` and lives inside the MolManager project directory.

---

## Part 4 — Create the virtual environment

Run **one** of the blocks below depending on your system.

### Windows (PowerShell)

```powershell
python -m venv .venv
```

If `python` is not found, try:

```powershell
py -3.11 -m venv .venv
```

### macOS / Linux

```bash
python3 -m venv .venv
```

This creates a `.venv` folder. It may take a minute. You only need to run this command **once** per project copy.

---

## Part 5 — Activate the virtual environment

You must **activate** the venv every time you open a **new** terminal window before installing or running MolManager. Activation tells the terminal to use the Python inside `.venv`.

### Windows (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
```

If you see an error about running scripts being disabled, run this **once** (as Administrator is not required for your user account):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

**Success looks like this:** your prompt starts with `(.venv)`, for example:

```text
(.venv) PS C:\Users\You\Documents\MolManager>
```

### Windows (Command Prompt)

```cmd
.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Your prompt should show `(.venv)` at the beginning.

> **Remember:** If you close the terminal or open a new one later, run the activate command again before starting MolManager.

---

## Part 6 — Install MolManager and its dependencies

With the virtual environment **active** (`(.venv)` visible in your prompt), run these commands **in order** from the MolManager project folder.

### Step 6a — Upgrade pip

`pip` is Python’s package installer. Upgrading it first avoids many common install errors.

**Windows**

```powershell
python -m pip install --upgrade pip
```

**macOS / Linux**

```bash
python3 -m pip install --upgrade pip
```

### Step 6b — Install dependencies

**Core desktop (recommended if you do not need pKa / permeability / docking ML):** smaller download, no PyTorch.

```bash
pip install -r requirements-core.txt
```

**Full stack:** desktop app plus machine-learning tools (PyTorch, Uni-pKa / unipkainfer, Chemprop), docking helpers (Meeko), and development tools (pytest). It can take **15–30 minutes** depending on your internet speed.

```bash
pip install -r requirements.txt
```

See [docs/PACKAGING.md](docs/PACKAGING.md) for install profiles and release versioning.

### Step 6c — Register the MolManager application

This step installs the MolManager program itself so you can launch it with `python -m molmanager`:

```bash
pip install -e .
```

The `-e` means “editable”: if you update the source code later, you do not need to reinstall.

**When everything succeeds**, you should see no red `ERROR` lines at the end. Warnings in yellow are usually fine.

---

## Part 7 — Start MolManager

Make sure the virtual environment is still active (`(.venv)` in your prompt), then run:

```bash
python -m molmanager
```

The MolManager window should open. Use **File → Open File** to load an SDF, SMILES, or CSV file.

### Starting MolManager later (after you closed the terminal)

Every time you want to use MolManager:

1. Open PowerShell or Terminal.
2. Go to the MolManager folder (`cd` to the project directory).
3. Activate the venv (Part 5).
4. Run `python -m molmanager`.

---

## Optional — Extra setup

Most Python packages are already installed by **Step 6b**. The items below are binaries or data files that are not installed by pip.

### pKa / PyTorch repair

If **Tools → Predict → pKa** fails with a PyTorch version error (often after installing another package that upgrades torch), run this in the **same** venv — do **not** create a second environment:

**Windows:**

```powershell
.\scripts\install_pytorch_pka.ps1
```

**macOS / Linux:**

```bash
bash scripts/install_pytorch_pka.sh
```

This removes conflicting packages (such as **admet-ai**) and reinstalls from `requirements.txt` (CPU PyTorch). With an NVIDIA GPU, pass `-Cuda` (Windows) or `--cuda` (macOS/Linux) to replace that wheel with the CUDA 12.4 build so **Predict pKa** can run on the GPU. The first **Predict pKa** run downloads Uni-pKa fold weights from Hugging Face (`unipka-download-model`). For offline machines, prefetch with that CLI or copy the fold into unipkainfer’s `model_dir`.

### Docking (EasyDock)

Table docking is **Tools → Dock → EasyDock…**. Receptor PDBQT still comes from **Prepare → Receptor PDB…** then **Prepare → PDBQT…**. Ligands are prepared by EasyDock/Meeko from table structures. Python pieces are in the docking extra (`pip install -e ".[docking]"` or `requirements.txt`). Protein Viewer **Prepare…** GAFF2 ligand min also needs OpenFF Toolkit from conda-forge (`conda install -c conda-forge openff-toolkit`) on Linux, macOS, or WSL — it is not on PyPI and is not supported on native Windows.

The **Smina** engine is not included in the Python install. Download a binary from [https://sourceforge.net/projects/smina](https://sourceforge.net/projects/smina) or your package manager, then either:

- Put `smina.exe` (Windows) or `smina` (macOS/Linux) in:
  - `molmanager/resources/bin/win/` (Windows)
  - `molmanager/resources/bin/mac/` (macOS)
  - `molmanager/resources/bin/linux/` (Linux)
- Or set the environment variable `MOLMANAGER_BUNDLE_DIR` to a folder that contains the executable.

The optional **Vina** engine needs `pip install vina` (often Linux/macOS only). **Smina…** remains for file-based PDBQT runs without table writeback.

See **Tools → Dock** in the app after the binary is in place.

### Systematic conformers (Open Babel)

**Tools → Conformations → Generate Conformations → Systematic…** uses Open Babel Confab. Open Babel is a project dependency (`pip install openbabel`, also in `requirements-core.txt`). The dialog defaults to that wheel’s `obabel` (`site-packages/openbabel/bin/obabel`). You can still override the path, or place `obabel.exe` / `obabel` under `molmanager/resources/bin/<platform>/` to prefer a bundled copy.

Distance-geometry ensembles remain **Generate Conformations → Stochastic…** (RDKit ETKDG; no Open Babel).

### Guided optional setup script

**Windows:**

```powershell
.\scripts\bootstrap_optional_tools.ps1
```

**macOS / Linux:**

```bash
bash scripts/bootstrap_optional_tools.sh
```

This runs `pip install -r requirements.txt`, `pip install -e .`, and can download permeability model weights.

### Permeability model weights

The Chemprop Python packages are in `requirements.txt`, but the **GNN-MTL model file** is not stored in git. Download it once:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

---

## Troubleshooting

### “python is not recognized” (Windows)

Python was not added to PATH. Reinstall Python from python.org and check **Add python.exe to PATH**, or use `py -3.11` instead of `python` in the commands above.

### “cannot be loaded because running scripts is disabled” (Windows PowerShell)

Run once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the venv again.

### RDKit or NumPy errors (`_ARRAY_API`, import failures)

MolManager pins **NumPy 1.x** because current RDKit wheels are not compatible with NumPy 2.x. Reinstall dependencies:

```bash
pip install -r requirements.txt --force-reinstall
```

If `rdkit-pypi` still fails on your system, use **conda** for RDKit and pip for the rest:

```bash
conda create -n molmanager python=3.11
conda activate molmanager
conda install -c conda-forge rdkit pyqt
pip install -r requirements.txt
pip install -e .
```

### PyQtWebEngine fails to install

The app can still run; the **View in 3D** feature may open structures in your web browser instead of an embedded viewer. On Linux you may need system packages (for example `libegl1` on Debian/Ubuntu).

### “No module named molmanager”

You skipped **Step 6c**. With the venv active, run:

```bash
pip install -e .
```

### pKa / PyTorch conflicts

Use **one** environment only. Run `scripts\install_pytorch_pka.ps1` or `bash scripts/install_pytorch_pka.sh` in the same venv where MolManager is installed. Do not install **admet-ai** in that environment.

### Apple Silicon (M1/M2/M3 Mac)

Core MolManager runs natively. If pKa fails on Apple Silicon, run `bash scripts/install_pytorch_pka.sh` to reinstall the CPU PyTorch stack from `requirements.txt`.

---

## Quick reference (experienced users)

```bash
# One-time setup (from repo root)
python -m venv .venv
# Windows:  .\.venv\Scripts\Activate.ps1
# macOS/Linux:  source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .

# Run
python -m molmanager

# Repair pKa / PyTorch conflicts (same venv)
# Windows:  scripts\install_pytorch_pka.ps1
# Unix:     bash scripts/install_pytorch_pka.sh

# Tests (pytest is already in requirements.txt)
# Windows:  set QT_QPA_PLATFORM=offscreen
# Unix:     export QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -v
```

Editable install extras in `pyproject.toml` (`pka`, `permeability`, `docking`, `dev`) mirror subsets of `requirements.txt` for `pip install -e ".[extra]"` workflows. Prefer `requirements-core.txt` when you only need the table desktop app.

Packaging and installer builds: `docs/PACKAGING.md`.

---

## Configuration (environment variables)

Optional settings for power users and IT deployments:

| Variable | Purpose |
|----------|---------|
| `MOLMANAGER_LOG_LEVEL` | Console log level: `DEBUG`, `INFO`, `WARNING`, … (default `INFO`) |
| `MOLMANAGER_MAX_THREADPOOL` | Main background thread pool size (`1`–`64`; default scales with CPU, cap `16`) |
| `MOLMANAGER_RENDER_THREADPOOL` | 2D structure render pool (`1`–`32`) |
| `MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS` | Row count for async substructure filtering (default `400`) |
| `MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_ROWS` / `MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_MS` | Debounce when a substructure filter is active |
| `MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_ROWS` / `MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_MS` | Debounce for other filters |
| `MOLMANAGER_PERF_METRICS` | Enable performance metric logging |
| `MOLMANAGER_PERF_LOG_EVERY` | Perf log interval (default `25` samples) |
| `MOLMANAGER_PLOT_SCATTERGL_MIN_POINTS` | Upgrade marker scatters to WebGL above this count (default `2000`) |
| `MOLMANAGER_PLOT_SELECTION_OVERLAY_MAX` | Max points for SVG/3D selection overlay; larger sets use selectedpoints / skip 3D overlay (default `400`) |
| `MOLMANAGER_CONFORMER_THREADS` | Parallel workers for conformer generation (`1`–`16`) |
| `MOLMANAGER_DESCRIPTOR_THREADS` | Parallel workers for descriptors (`1`–`32`) |
| `MOLMANAGER_PROTOMER_PROCESSES` | Parallel processes for Protonate and Generate Protomers (`1`–`8`) |
| `MOLMANAGER_SQL_MAX_ROWS_HARD` | Hard cap for SQL load row count (default `2000000`) |
| `MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_ROWS` | Hard cap for Diverse Subset pool size (default `200000`) |
| `MOLMANAGER_DIVERSE_SUBSET_EXACT_MAX_ROWS` | Auto mode uses Exact MaxMin at or below this size (default `50000`) |
| `MOLMANAGER_DIVERSE_SUBSET_FAST_CANDIDATE_CAP` | Fast-mode candidate pool size before MaxMin (default `10000`) |
| `MOLMANAGER_SQL_PRECOUNT_WARN` | Confirm before loading if `COUNT(*)` ≥ this (default `100000`) |
| `MOLMANAGER_SQLITE_TIMEOUT_S` | SQLite connection timeout seconds (default `30`) |
| `MOLMANAGER_PG_CONNECT_TIMEOUT` | PostgreSQL connect timeout seconds (default `30`) |
| `MOLMANAGER_SQLITE_BACKEND_PAGE_SIZE` | SQLite cache page size for filters (default `5000`) |
| `MOLMANAGER_DISABLE_CUSTOM_CALC` | Set to `1` / `true` to disable Tools → Custom Calculator |
| `MOLMANAGER_LOG_DIR` | Directory for rotating `molmanager.log` (platform default under user app data / state) |
| `MOLMANAGER_LOG_TO_FILE` | Set to `0` / `false` to disable file logging (console only) |
| `MOLMANAGER_BUNDLE_DIR` | Folder containing optional `vina` / `smina` binaries |

**Custom calculator:** expressions always use a restricted AST interpreter (`safe_calc`). Treat them as trusted input only. `MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL` is retired and ignored if set.

**Legacy env aliases:** `CHEMMANAGER_*` variables are still mapped to `MOLMANAGER_*` when the new name is unset, with a deprecation warning. Prefer `MOLMANAGER_*` only.

**Logs:** MolManager writes a rotating log file (default on) and shows the path in the crash dialog on uncaught exceptions.
**SQL URLs in logs:** at `DEBUG`, connection URLs are logged with credentials redacted.

---

## Project layout

| Path | Role |
|------|------|
| `molmanager/app.py` | Application entry point |
| `molmanager/ui/main_window/` | Main window and feature mixins |
| `molmanager/ui/compound_table_model.py` | Table data model |
| `molmanager/ui/dialogs/` | Tool dialogs |
| `molmanager/workers/` | Background jobs (render, export, cluster, pKa, …) |
| `molmanager/storage/` | SQLite mirror for fast filtering |
| `docs/ARCHITECTURE.md` | How components fit together |
| `docs/STEREO_AND_ISOMERISM.md` | Stereochemistry behavior |
| `docs/VALENCE_BONDS_AND_AROMATICITY.md` | Sketcher bond and valence rules |

---

## Development

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for coding standards, Ruff, GPL headers, and CI expectations.

**Tests** (with venv active; pytest is included in `requirements.txt`):

Windows:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest tests/ -v
```

macOS / Linux:

```bash
export QT_QPA_PLATFORM=offscreen
python -m pytest tests/ -v
```

CI runs lint (Ruff + GPL headers) on Ubuntu, and tests on Ubuntu, macOS, and Windows for pushes and pull requests to `main` and `dev` (see `.github/workflows/ci.yml`). Linux also runs the 100k performance gate and a CRITICAL/HIGH/malware `pip-audit` gate (`scripts/check_dependency_audit.py`).

**Lint / headers:**

```bash
python -m ruff check molmanager tests scripts
python scripts/check_gpl_headers.py
```

**Performance benchmark:**

```bash
python scripts/benchmark_large_table.py --runs 3 --scales 10000,50000,100000
```

---

## Stereochemistry and structures

MolManager (RDKit + the 2D sketcher) handles **tetrahedral** stereo and **alkene E/Z** from 2D layout. It does not automatically enumerate tautomers or atropisomers. See `docs/STEREO_AND_ISOMERISM.md` and `docs/VALENCE_BONDS_AND_AROMATICITY.md` before changing structure-related code.

---

## License

Copyright (C) 2026 Hunter Picard

MolManager is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

The full license text is in [LICENSE](LICENSE).
