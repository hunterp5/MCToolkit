# Predict pKa

Predict pKa writes Uni-pKa **macro pKa** values into a column (or previews them from a SMILES string). Optional **Calculate isoelectric point (pI)** also writes **pI**. Most-acidic and most-basic checkboxes keep a single pKa number (min / max of those macros); pI, when requested, is still from the full ensemble.

For amines this is the aqueous pKa of the **conjugate acid** (BH+ ⇌ B + H+), which is the number tabulated in references (dimethylamine ≈ 10.7, not the much higher pKa of the free base as an acid). Uni-pKa’s free-energy head is trained on mean-centered Dwar targets; MCtoolkit adds that mean so the table matches the official aqueous scale. Older **UniPka** sample columns written before that shift sit near ~4–6 for aliphatic amines and should be ignored — re-run **Predict pKa** / **Protonate** to refresh the shared **pKa** column.

## Goal

Estimate aqueous ionization constants for table molecules using the same Uni-pKa ensemble that Protonate, Generate Protomers, LogD 7.4, LogS 7.4, CNS MPO, and AB-MPS share.

## When to use

Use before pH-dependent descriptors or protonation tools, or when you need a tabulated pKa for filtering. Re-running after the former pkasolver engine is a **new method**, not a refresh of old numbers.

## Inputs / scope

A structure column or a SMILES string. Optional **Selected Rows Only**. Requires the **pka** extra (`unipkainfer`). The first run downloads Uni-pKa fold weights from Hugging Face (`unipka-download-model`; optional `model_dir` for offline copies).

## Options

- **Input** — table column or SMILES.
- **Most basic only** / **Most acidic only** — single pKa value instead of the full macro-pKa list.
- **Calculate isoelectric point (pI)** — also write a shared **pI** column (pH where mean charge crosses zero; N/A for simple acids/bases). Off by default.
- **Selected Rows Only** — limit to the selection.

## Workflow

1. Choose the structure source or paste SMILES.
2. Optionally restrict to most acidic or most basic, and optionally calculate pI.
3. Predict and wait for **Processes** to finish.
4. Later Protonate / LogD jobs reuse the session cache for the same structures. **Save Session** writes those ensembles into the ``.cms`` file so Open / Duplicate does not need to re-run Uni-pKa.

## Tips and limits

CPU inference scores every enumerated microstate (11 MMFF conformers × Uni-Mol). Duplicate structures are predicted once and reused from the session cache (Protonate / LogD / Generate Protomers). Unique structures are scored in batches of up to 16 so one Uni-pKa call covers several molecules. The cache is also restored from saved sessions; SDF/CSV export does not include it. The **pKa** column is shared: Protonate, LogD/LogS 7.4, CNS MPO, AB-MPS, and Generate Protomers update the same header in place. **pI** is written only when Predict pKa is run with **Calculate isoelectric point** checked.

Speed: Uni-pKa runs on **CUDA** in a worker process when this Python’s PyTorch is a CUDA wheel. That worker stays loaded between jobs so the next Predict pKa / Protonate does not reload fold weights. Closing the app terminates it. The default `requirements.txt` install is a CPU wheel. With an NVIDIA GPU, run `scripts\install_pytorch_pka.ps1` or `bash scripts/install_pytorch_pka.sh` — CUDA is selected automatically when `nvidia-smi` sees a GPU (pass `-Cpu` / `--cpu` to keep the CPU wheel). The optional bootstrap scripts do the same. If MCtoolkit is already running on a CPU wheel, Predict pKa / Protonate shows a one-time reminder. Force CPU scoring with `MOLMANAGER_PKA_GPU=0`. On CPU, auto process-pool workers (override with `MOLMANAGER_PKA_PROCESS_WORKERS`, 1–8) and MMFF thread count (`MOLMANAGER_UNIPKA_MMFF_THREADS`) can be tuned. Values will differ from historical pkasolver columns. Re-running Predict pKa (or Protonate / LogD) updates the shared **pKa** column in place; **pI** is updated in place only when that option is on. Other descriptor names still get ``Name (1)`` writeback.
