# SQL Database

SQL Database loads query results from a configured SQL connection into the MCToolkit table for further chemistry work.

## Goal

Pull structured corporate or local database rows (including SMILES/properties) without manual CSV export.

## When to use

Use when your compounds/assays live in a database you can query from this machine.

## Inputs / scope

Requires a reachable database and a valid SQL query returning tabular columns; structure columns must be interpretable as molecules when you plan chemistry tools.

## Options

- **Connection** - database settings as presented in the dialog.
- **SQL query** - editor and execution controls.
- **Load results** - bring the result set into the current table/session.
- **Column mapping** - follows query result names into table headers.

## Workflow

1. Open **Tools → Query Database → SQL…**.
2. Configure connection details.
3. Write and run a SQL query limited to what you need.
4. Load results into the table.
5. Assign structure sources and proceed with MCToolkit tools.

## Use cases

- Fetch a project registry slice by assay campaign.
- Join IDs to SMILES in-database then analyze locally.
- Refresh a saved query after new experimental uploads.

## Tips and limits

Credentials and network access are your responsibility — do not embed secrets in shared sessions carelessly. Prefer **SELECT** queries. The dialog defaults to a **read-only connection** (SQLite opens with `mode=ro`) and blocks SQL that looks destructive (INSERT/UPDATE/DELETE/DROP/…). Uncheck read-only only when you intentionally need a write connection, and confirm the warning. Large result sets can overwhelm memory; filter in SQL first and use **Max rows**. Invalid SMILES still fail chemistry tools after load.
