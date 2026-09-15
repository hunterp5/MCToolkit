# Bundled resources

## Static assets (in repository)

- **3Dmol.js** — `molmanager/ui/static/3Dmol-min.js` (offline 3D viewer)

## Optional CLI binaries (not in git — place locally or use installer)

molmanager can run these when installed on the system **or** when copied into:

```
molmanager/resources/bin/win/     # Windows: vina.exe, smina.exe, optional obabel.exe
molmanager/resources/bin/linux/ # Linux
molmanager/resources/bin/mac/   # macOS
```

Override the search directory with environment variable `MOLMANAGER_BUNDLE_DIR`.

| Tool | License / size | Install |
|------|----------------|---------|
| **AutoDock Vina / smina** | Academic/free; small binary | [vina.scripps.edu](https://vina.scripps.edu) — copy `vina` / `vina.exe` (or `smina`) into `bin/<platform>/` |
| **Open Babel (`obabel`)** | GPL; Confab systematic conformers | `pip install openbabel` (project dependency). Systematic defaults to the wheel’s `openbabel/bin/obabel`. Optional: copy `obabel` into `bin/<platform>/` to override. |

Python dependencies (RDKit, PyQt5, PyTorch, unipkainfer, Chemprop, Meeko, pytest) are installed via `pip install -r requirements.txt` and `pip install -e .` — see root **README** and **docs/PACKAGING.md**.

## GNN-MTL permeability model (optional, not in git)

`molmanager/resources/models/gnn_mtl/model.pt` — see `models/gnn_mtl/README.md`. Download:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

## BioTransformer 3 (optional, not in git)

`molmanager/resources/models/biotransformer/` — see `models/biotransformer/README.md`. Download:

```bash
python scripts/bootstrap_biotransformer.py
```

Requires Java on PATH plus the official JAR (`BioTransformer3.0_20230525.jar` or `biotransformer-3.0.0.jar`) with sibling `btkb/` or `database/` and `supportfiles/`. Override the JAR with `MOLMANAGER_BIOTRANSFORMER_JAR`, or use **Browse JAR…** in Predict Metabolites.
