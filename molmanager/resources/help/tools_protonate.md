# Protonate

Protonate writes the dominant protomer at a chosen pH into an output column using a **Uni-pKa** ionization ensemble (MolGpKa SMARTS enumeration + Uni-Mol free energies). It also writes **% Protomer**, the Boltzmann mole fraction of that form at the dialog pH. Optional **Render 2D** depicts that column the same way as **Structure** (image cells; SMILES stay stored, not shown as text).

## Goal

Produce pH-relevant ionization states for permeability-minded prep, docking ligands, or consistent descriptor calculation.

## When to use

Use when default microstates are wrong for your assay pH, or before comparisons that depend on charge state. For the full ensemble at that pH, use **Generate Protomers** instead.

## Inputs / scope

Input structures from the selected source; optional **Selected Rows Only**. Requires Uni-pKa (`unipkainfer`). Duplicate structures are predicted once and reused; a session cache is shared with Predict pKa and LogD/LogS so a second run on the same molecules is cheap.

## Options

- **Structure source** - which structure column to read.
- **pH** - target pH for dominant protomer selection.
- **Output column** - destination column name.
- **Selected Rows Only** - limit to the selection.
- **Render 2D in output column** - depict the output column like **Structure** (pixmap cells). Unchecked leaves SMILES text.
- **Run** - start the job.

## Workflow

1. Set structure source, **pH**, and output column.
2. Choose full table or **Selected Rows Only**.
3. Run and wait for completion.
4. Point later tools at the output column as structure source. Check **% Protomer** if the top form is only a slim majority.

## Use cases

- Protonate at pH 7.4 before medchem property plots.
- Prepare ligands at physiological pH for docking.
- Compare acidic vs basic series at a shared pH.

## Tips and limits

Populations are Boltzmann weights of Uni-pKa free energies at the dialog pH (not independent-site Henderson–Hasselbalch). **% Protomer** below ~80% means other forms still matter; use **Generate Protomers**. Parallelism is `MOLMANAGER_PROTOMER_PROCESSES` (`1`–`8`). Always keep the original column if you need neutral parents. Re-running after pkasolver is a new method, not a refresh.
