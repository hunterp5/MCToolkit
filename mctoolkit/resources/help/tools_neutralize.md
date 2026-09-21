# Neutralize

Neutralize attempts to zero net formal charge using RDKit's Uncharger so structures are closer to standard neutral parents.

## Goal

Standardize charged salts/ionized forms toward neutral molecules for clustering and many descriptor workflows.

## When to use

Use on purchased libraries with charged nitrogens/acids, or after imports that preserve ionic states you do not want.

## Inputs / scope

Scoped structure rows; optional **Selected Rows Only**.

## Options

- Structure source.
- **Selected Rows Only** when available.
- Apply Uncharger-based neutralization.
- Run / OK to execute.

## Workflow

1. Scope the rows to neutralize.
2. Run **Neutralize**.
3. Check formal charges and depictions.
4. Continue with descriptors or Fast Prepare as needed.

## Use cases

- Neutralize vendor salts before fingerprint clustering.
- Standardize before MMP fragmentation.
- Clean ionized SMILES from ELN exports.

## Tips and limits

Neutralization is heuristic and may not match biological ionization. For pH-specific states prefer Protonate. Zwitterions and unusual charge pairs deserve manual review.
