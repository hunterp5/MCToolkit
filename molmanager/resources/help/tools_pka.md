# Predict pKa

Predict pKa writes Uni-pKa **macro pKa** values into a column (or previews them from a SMILES string), plus **pI** (isoelectric point). Most-acidic and most-basic checkboxes keep a single pKa number (min / max of those macros); pI is still from the full ensemble.

## Goal

Estimate aqueous ionization constants for table molecules using the same Uni-pKa ensemble that Protonate, Generate Protomers, LogD 7.4, LogS 7.4, CNS MPO, and AB-MPS share.

## When to use

Use before pH-dependent descriptors or protonation tools, or when you need a tabulated pKa for filtering. Re-running after the former pkasolver engine is a **new method**, not a refresh of old numbers.

## Inputs / scope

A structure column or a SMILES string. Optional **Selected Rows Only**. Requires the **pka** extra (`unipkainfer`). The first run downloads Uni-pKa fold weights from Hugging Face (`unipka-download-model`; optional `model_dir` for offline copies).

## Options

- **Input** — table column or SMILES.
- **Most basic only** / **Most acidic only** — single pKa value instead of the full macro-pKa list. **pI** is still written from the ensemble.
- **Selected Rows Only** — limit to the selection.

## Workflow

1. Choose the structure source or paste SMILES.
2. Optionally restrict to most acidic or most basic.
3. Predict and wait for **Processes** to finish.
4. Later Protonate / LogD jobs reuse the session cache for the same structures. **Save Session** writes those ensembles into the ``.cms`` file so Open / Duplicate does not need to re-run Uni-pKa.

## Tips and limits

CPU inference scores every enumerated microstate (11 MMFF conformers × Uni-Mol). Duplicate structures are predicted once and reused from the session cache (Protonate / LogD / Generate Protomers). Unique structures are scored in batches so one Uni-pKa call covers several molecules. The cache is also restored from saved sessions; SDF/CSV export does not include it.

Speed: Uni-pKa runs on **CUDA** in a worker process when this Python’s PyTorch is a CUDA wheel. Closing the app terminates that worker. The default `requirements.txt` install is a CPU wheel — with an NVIDIA GPU, reinstall the CUDA build (`scripts\install_pytorch_pka.ps1 -Cuda` or `bash scripts/install_pytorch_pka.sh --cuda`). Force CPU with `MOLMANAGER_PKA_GPU=0`. On CPU, auto process-pool workers (override with `MOLMANAGER_PKA_PROCESS_WORKERS`, 1–8) and MMFF thread count (`MOLMANAGER_UNIPKA_MMFF_THREADS`) can be tuned. Values will differ from historical pkasolver columns; unique-column writeback avoids silent overwrite.
