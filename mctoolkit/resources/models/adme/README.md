# ADME Chemprop models (ADMET-AI v2 weights)

**Source:** Swanson et al., *ADMET-AI: a machine learning ADMET platform for evaluation of large-scale chemical libraries*, Bioinformatics 2024.  
**Artifact:** [Zenodo 10.5281/zenodo.18728250](https://doi.org/10.5281/zenodo.18728250) — `admet_classification/` and `admet_regression/` (Chemprop v2, 5-fold ensembles).

These are used by **Tools → Predict → ADME**. mctoolkit does not install the `admet-ai` package.

Place the ensemble folders in this directory, or run from the repo root:

```bash
python scripts/bootstrap_adme_models.py
```

Override path with environment variable `MCTOOLKIT_ADME_MODELS`.

Local v2 predictions will not match the public ADMET-AI website (v1). TDC outputs are QSAR scores, not measured assays. Use **Predict Permeability** for GNN-MTL Caco-2 / MDCK efflux.
