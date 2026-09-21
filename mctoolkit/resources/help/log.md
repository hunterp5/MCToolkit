# Log

The session log is the lower pane of **Processes**: a transcript of tool output, status-bar history, warnings, and application logging. Use it when the status bar is too brief and per-tool logs are too scattered.

## Goal

Follow complex or long-running work (docking, protein prep, large table jobs) without losing earlier messages when the status line updates.

## When to use

Open **Processes** while a job is running, after a failure, or when you need to copy details for support. The log is below the job table.

## Inputs / scope

The in-memory log covers the current mctoolkit process. It is not saved with the session. A rotating file log is still written under the user log directory when file logging is enabled.

## Options

- **Level** - hide records below Debug, Info, Warning, or Error.
- **Filter text** - match logger name or message.
- **Auto-scroll** - keep the view pinned to new lines.
- **Copy** - copy the visible text.
- **Clear** - empty the in-memory log (does not delete the log file).
- **Open log file** - open the rotating `mctoolkit.log` in the default editor when file logging is on.

## Workflow

1. Start a tool that runs in the background or writes detailed output (Gnina, PDBFixer, pdb2pqr, descriptors, and similar).
2. Open **Processes**. The table shows job status and cancel; the pane below keeps the narrative.
3. Filter by level or search if the transcript is long.
4. **Copy** or **Open log file** when you need to keep the details.

## Use cases

- Reconstruct why a docking or protein-prep step failed after the status bar moved on.
- Confirm a long descriptor or conformer job started and finished (0% / 100% and completion messages).
- Collect warnings from the same run that would otherwise only exist in the log file.

## Tips and limits

The status bar still shows the latest line only; the log keeps history. Progress percents between 0% and 100% are omitted so chunked jobs stay readable. Clearing the log does not cancel jobs — use the table above for that. The in-memory buffer is capped; older lines drop off on very long sessions, while the log file keeps rotating backups.
