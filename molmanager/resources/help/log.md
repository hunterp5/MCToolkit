# Log

The Log window lists background jobs (descriptor calculation, clustering, exports, conformer builds, and similar) with status, cancel, and queue controls. The session log sits below the job table.

## Goal

Monitor, cancel, or clear queued work so heavy chemistry jobs do not block the UI, and keep the transcript of tool output, status history, and warnings in the same window.

## When to use

Use whenever a tool starts a background worker, when the UI feels busy, when you need to stop a long run before it finishes writing columns, or when you need the detailed log after a failure.

## Inputs / scope

Applies to jobs launched from the current session. Scope of each job (all rows vs selected) was chosen in the tool dialog that started it. The in-memory log covers the current MolManager process and is not saved with the session.

## Options

- Job list showing running and queued work, including live **Progress** (the same counts shown in the status bar).
- **Cancel Job** - stop the active or selected job when the worker supports cancellation.
- **Clear Queue** - drop pending jobs that have not started yet.
- **Level / Filter text / Auto-scroll** - transcript controls on the same footer row as Cancel and Clear Queue.

## Workflow

1. Start a tool that runs asynchronously.
2. Open **Log** to confirm the job appears and progresses. Progress stays in that window even if the status bar is later overwritten. The pane below keeps the narrative.
3. **Cancel Job** if you launched the wrong scope or settings.
4. **Clear Queue** to remove jobs waiting behind a long run.

## Use cases

- Stop a descriptor or conformer job that was applied to the full table by mistake.
- Clear a backlog of plot/export jobs after changing filters.
- Confirm a docking or enumeration job finished before exporting.
- Reconstruct why a docking or protein-prep step failed after the status bar moved on.

## Tips and limits

Not every step is instantly interruptible; cancel may finish the current chunk before stopping. Clearing the queue does not undo columns already written. The status bar still shows the latest line only; the log keeps history. Progress percents between 0% and 100% are sampled so chunked jobs stay readable. The in-memory buffer is capped; older lines drop off on very long sessions, while the rotating file log keeps backups.
