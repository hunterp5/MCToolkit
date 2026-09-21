# Cluster

Cluster groups molecules by fingerprint similarity using methods such as K-Means, Agglomerative, DBSCAN, Butina, sphere exclusion, and Jarvis-Patrick, with an optional exploratory trial mode.

## Goal

Partition a library into clusters for series assignment, exemplars, or stratified follow-up.

## When to use

Use after cleanup when you need structure-based grouping rather than a single diverse subset.

## Inputs / scope

Fingerprints from **Source** structures; optional **Selected Rows Only**. Exploratory mode samples many parameter sets before you apply one trial.

## Options

- **Source** - structure column.
- **Selected Rows Only** - scope.
- **Fingerprint** - FP type for clustering.
- **Exploratory mode** - sample many parameter sets; **Max trials**.
- **Methods to sample** / **Method** - **K-Means**, **Agglomerative**, **DBSCAN**, **Butina (Tanimoto)**, **Sphere exclusion (Leader)**, **Jarvis-Patrick**.
- Method parameters - **Clusters (k)**, **Linkage**, **eps**, **min_samples**, **Distance cutoff**, **Reordering**, **Nearest neighbors (J)**, **Shared neighbors (P)**.
- **Run clustering** / **Apply selected trial**.

## Workflow

1. Choose structure source, FP, and scope.
2. Either set one method/parameters or enable **Exploratory mode**.
3. Run clustering and review trial/cluster labels.
4. Apply the chosen trial and use cluster IDs in filters/plots.

## Use cases

- Assign series labels for medchem reporting.
- Compare Butina cutoffs in exploratory mode.
- Cluster only selected actives for SAR grouping.

## Tips and limits

No single method is best for every library - validate chemically. DBSCAN/Butina parameters are scale-sensitive. Large N × exploratory trials can be slow; watch **Processes**.
