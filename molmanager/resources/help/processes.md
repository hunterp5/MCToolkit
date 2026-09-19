# Processes

The Processes panel lists background jobs (descriptor calculation, clustering, exports, conformer builds, and similar) with status, cancel, and queue controls. The session log sits below the job table.

## Goal

Monitor, cancel, or clear queued work so heavy chemistry jobs do not block the UI, and keep the transcript of tool output, status history, and warnings in the same window.

## When to use

Use whenever a tool starts a background worker, when the UI feels busy, when you need to stop a long run before it finishes writing columns, or when you need the detailed log after a failure.

## Inputs / scope

Applies to jobs launched from the current session. Scope of each job (all rows vs selected) was chosen in the tool dialog that started it. The in-memory log covers the current MCtoolkit process and is not saved with the session.

## Options

- Job list showing running and queued work, including live **Progress** (the same counts shown in the status bar).
- **Cancel** - stop the active or selected job when the worker supports cancellation.
- **Clear queue** - drop pending jobs that have not started yet.
- **Log** (below the table) - level filter, text search, copy, clear, and open the rotating log file. See **Log** for the full transcript options.

## Workflow

1. Start a tool that runs asynchronously.
2. Open **Processes** to confirm the job appears and progresses. Progress stays in that window even if the status bar is later overwritten. The log below keeps the narrative.
3. **Cancel** if you launched the wrong scope or settings.
4. **Clear queue** to remove jobs waiting behind a long run.

## Use cases

- Stop a descriptor or conformer job that was applied to the full table by mistake.
- Clear a backlog of plot/export jobs after changing filters.
- Confirm a docking or enumeration job finished before exporting.
- Reconstruct why a docking or protein-prep step failed after the status bar moved on.

## Tips and limits

Not every step is instantly interruptible; cancel may finish the current chunk before stopping. Clearing the queue does not undo columns already written. Clearing the log does not cancel jobs. Keep an eye on memory for very large libraries.
