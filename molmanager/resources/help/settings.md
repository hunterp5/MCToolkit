# Settings

Settings control appearance, keyboard shortcuts, and the WSL executable used for Linux-only tools: themes, application/table fonts, the hotkey editor, whether the status bar is shown, and Windows Subsystem for Linux.

## Goal

Make MCtoolkit readable and efficient for your display and preferred shortcuts without changing chemistry results.

## When to use

Adjust when switching light/dark preference, changing monitor DPI, or customizing shortcuts for frequent tools.

## Inputs / scope

Global UI preferences for this installation/session; they do not alter table chemistry data.

## Options

- **Light Mode** / **Dark Mode** / **Groovy Mode** - built-in themes.
- **Custom Colors...** - edit named custom themes (palette roles, save/delete).
- **Status Bar** - under **GUI**; show or hide the bottom bar (status messages and memory use).
- **2D Render...** - pixel size of 2D structure drawings in the Structure column.
- **Font...** - **Application font size**, **Table font size**, **Table text alignment** (3×3: top/center/bottom × left/center/right), **Reset to Default**.
- **Hotkeys...** - category/command/shortcut table with **Reset to Defaults**, **Clear Selected**, and OK/Cancel.
- **WSL...** - path to ``wsl.exe`` so Windows can run Linux-only tools (AmberTools / GAFF for OpenMM, and similar). **Test** runs ``uname -s`` inside WSL.

## Workflow

1. Open **Settings** and pick a theme or **Custom Colors...**.
2. Set font sizes so the table and dialogs stay readable.
3. Edit hotkeys for commands you use often; reset if a binding conflicts.
4. On Windows, set **WSL...** if you will run Linux-only tools such as GAFF/AmberTools.
5. Confirm changes and return to the table.

## Use cases

- Dark theme for long evening analysis sessions.
- Larger table font for dense numeric columns.
- Bind a hotkey to Filters or Plotter for rapid iteration.

## Tips and limits

Theme and font changes are visual only. Hotkey conflicts can leave a command unreachable until cleared or reset. Custom themes are saved by name - delete unused ones to keep the list short.
