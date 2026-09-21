# Predict ADME

Predict ADME writes **only the properties you check** into table columns. It scores molecules with Chemprop models trained on Therapeutics Data Commons (TDC) ADMET datasets. The weights are the published **ADMET-AI v2** checkpoints; mctoolkit does **not** install the `admet-ai` Python package.

## Goal

Estimate a selected panel of absorption, distribution, metabolism, excretion, and toxicity scores for table molecules without leaving the session.

## When to use

Use when you need a broad in-silico ADME panel (hERG, CYPs, BBB, bioavailability, clearance, and related TDC tasks). Keep **Predict Permeability** for GNN-MTL Caco-2 / MDCK efflux ratios, and **Predict pKa** / Protonate / LogD for Uni-pKa ionization.

## Inputs / scope

A structure column. Optional **Selected Rows Only**. Requires Chemprop (same extra as Predict Permeability) and the v2 checkpoints. If weights are missing, run `python scripts/bootstrap_adme_models.py`.

## Options

- **Properties** — grouped checkboxes. All start **unchecked**. Predict is blocked until at least one is checked.
- **Recommended** — checks a small default set (hERG, CYP3A4 inhibitor, oral bioavailability, BBB, DILI, PPB, hepatocyte clearance, aqueous solubility). Opt-in; not the initial state.
- **Select all** / **Clear** — check or uncheck every endpoint.
- **Selected Rows Only** — limit to the selection.

Classification tasks are probabilities in 0–1. Regression tasks are the TDC model scale (not converted to GNN-MTL permeability units). **Caco-2 Papp (TDC)** is a different assay/model than **Predict Permeability**.

## Workflow

1. Open **Tools → Predict → ADME…**.
2. Check the endpoints you want (or **Recommended**).
3. Choose the structure source and optional row scope.
4. Predict and wait for **Processes** to finish.

## Tips and limits

Local v2 numbers will **not** match the public ADMET-AI website, which still serves v1 models. TDC QSAR is not a substitute for measured assays; some endpoints are noisy or scaffold-biased. Do not `pip install admet-ai` into this environment — that package needs a newer PyTorch than Uni-pKa. CUDA Chemprop runs in the same worker process as Predict Permeability so the GUI never initializes the GPU. Force CPU with `MCTOOLKIT_ADME_GPU=0`. Override the weights directory with `MCTOOLKIT_ADME_MODELS`.
