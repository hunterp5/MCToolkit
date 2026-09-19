# GNN-MTL permeability model (Chemprop)

**Source:** Ohlsson et al., *Prediction of Permeability and Efflux Using Multitask Learning*, ACS Omega 2025.  
**Artifact:** [Zenodo 10.5281/zenodo.16948542](https://doi.org/10.5281/zenodo.16948542) — file `model.pt` (Chemprop v2.1.0).

Place `model.pt` in this directory, or run from the repo root:

```bash
python scripts/bootstrap_gnn_mtl_model.py
```

Override path with environment variable `MOLMANAGER_GNN_MTL_MODEL`.

**Model outputs (log10, in order):** Caco-2 ER, Caco-2 Papp, MDCK-MDR1 ER, NIH MDCK ER.

MCToolkit writes **linear** values to the table (10^prediction):

| Column in MCToolkit | Endpoint |
|----------------------|----------|
| Caco-2 ER | Caco-2 efflux ratio (unitless) |
| Caco-2 Papp | Caco-2 intrinsic apparent permeability (×10⁻⁶ cm/s) |
| MDCK-MDR1 ER | MDCK-MDR1 efflux ratio (not passive Papp) |
| NIH MDCK ER | NIH MDCK-MDR1 efflux ratio |

External public assays may differ in units and conditions from AstraZeneca training data.
