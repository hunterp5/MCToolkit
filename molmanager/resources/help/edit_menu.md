# Edit

The Edit menu covers undo/redo, clipboard operations, and selection commands that change table contents or the current selection set.

## Goal

Correct mistakes safely and move values or selections efficiently while editing the compound table.

## When to use

Use after accidental deletes/edits, when copying cells/structures, or when selecting all / inverting selection for scoped tools.

## Inputs / scope

Operates on the current table and selection. Undo depth depends on recent editable actions.

## Options

- **Undo** / **Redo** - reverse or reapply recent table edits.
- **Delete Selection** - delete selected rows, delete selected columns (when no rows are selected), or clear values from selected cells. When both rows and columns are selected, choose which to delete. Structure cannot be removed as a column.
- Clipboard commands (copy/paste as available).
- Selection commands (select all, clear, invert - per menu entries).
- Related edit actions exposed in the menu for the active table focus.

## Workflow

1. Make an edit or selection change.
2. Use **Undo** if the result is wrong.
3. Copy values as needed for external notes.
4. Shape selection before running **Selected Rows Only** tools.

## Use cases

- Undo a bulk column clear.
- Select all visible hits then invert to exclude them.
- Copy SMILES from selected cells into another app.

## Tips and limits

Not every background tool result is undoable the same way as cell edits - prefer session duplicates before destructive bulk jobs. Paste validity still depends on column types. Keep focus on the table for edit shortcuts to apply.
