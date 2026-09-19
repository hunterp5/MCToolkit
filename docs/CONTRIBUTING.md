# Contributing to MolManager

This document is the versioned source of project coding standards for humans and CI.
Cursor-specific copies live under [`.cursor/rules/`](../.cursor/rules/) (tracked in git).

## Coding standards

### Copyright headers

- Every **new** first-party source file must include the standard MolManager GPL copyright header.
- Keep a shebang as line 1 when present; put the header immediately below it.
- Do **not** add the header to vendored/third-party assets (e.g. `molmanager/ui/static/`).
- Full header text: [`.cursor/rules/copyright-headers.mdc`](../.cursor/rules/copyright-headers.mdc).
- Check: `python scripts/check_gpl_headers.py`
- Bulk insert: `python scripts/add_gpl_headers.py`

### Python style and formatting

- Follow **PEP 8** and keep code clean and maintainable.
- Format and lint Python with **Ruff** (`pyproject.toml` `[tool.ruff]`).
- Prefer **type hints** for public functions and non-trivial internal helpers.
- Avoid redundant comments; only comment on non-obvious intent or trade-offs.

```bash
python -m ruff check molmanager tests scripts
python -m ruff format molmanager tests scripts
```

CI gates on `ruff check` (correctness / undefined-name rules plus unused imports and locals:
`E9`, `F63`, `F7`, `F82`, `F401`, `F841`, plus the silent-exception ratchet `BLE001`, `S110`,
`SIM105`) and `ruff format --check`.

### Naming conventions

- **snake_case** for variables and functions.
- **PascalCase** for classes.
- Descriptive names; avoid single-letter names except conventional loop indices.

### Quality and correctness

- Fix problems at the **cause**, not the symptom.
- Keep the UI responsive by offloading heavy work off the GUI thread (`ProcessQueueManager`, `QThreadPool`, workers).
- Keep changes cohesive; avoid drive-by refactors unless required.
- New tools: dialog → worker (if heavy) → `WorkspaceTools` or collaborator + window forward → tests. Do **not** add mixin bases to `ChemistryWorkspaceWindow`. See [ARCHITECTURE.md](ARCHITECTURE.md) (Mixins vs composition).
- New menubar items go in `molmanager/ui/main_window/menu_spec.py` (plain data). `init_menubar` only installs that tree. See [ARCHITECTURE.md](ARCHITECTURE.md) (Main window).
- Put "can this run / what should happen next" decisions in `molmanager/workflows/`: plain-data arguments in, result object out, no Qt. The UI adapter renders the result. See [ARCHITECTURE.md](ARCHITECTURE.md) (Workflow layer).
- Most `*_mixin.py` files are file-splits of one host class. True mixins (shared by multiple classes) are filter-card chrome and `ProteinStructureSourceMixin` only.
- New collaborator methods use `self._app`. `bind_mixin_methods` is a legacy bridge.

### Exception handling

- Prefer narrow `except` clauses and re-raise unexpected failures.
- Do not use `except Exception: pass`. For a specific, expected failure use
  `contextlib.suppress(SomeError)` or handle the error. For a non-fatal path that must catch
  `Exception`, call `molmanager.platform_support.exception_policy.log_swallowed_exception` and add
  `# noqa: BLE001` with a short reason (worker/process boundary, Qt object already deleted, and
  similar).
- New `except Exception` / `try-except-pass` in files that are not on the allowlist fail CI
  (`BLE001`, `S110`, `SIM105`). Existing sites are listed in [`ruff.exception-ratchet.toml`](../ruff.exception-ratchet.toml).
  When you clean a file, delete its line there, decrement `ratchet-max-files`, and lower
  `EXCEPTION_RATCHET_MAX_FILES` in `tests/test_exception_ratchet.py`. Never add files.
- File logging is on by default (`molmanager/platform_support/app_logging.py`); override with `MOLMANAGER_LOG_DIR`,
  disable with `MOLMANAGER_LOG_TO_FILE=0`. Uncaught exceptions show a crash dialog with the log path.

### Architecture ratchet

- Coupling counters are frozen in [`architecture-ratchet.json`](../architecture-ratchet.json) and gated by
  `tests/test_architecture_ratchet.py` plus CI. They may only go **down**.
- Report: `python scripts/architecture_metrics.py`. Blame a metric:
  `python scripts/architecture_metrics.py --offenders rdkit_in_ui_modules`.
- After a cleanup lands, re-freeze: `python scripts/architecture_metrics.py --write-baseline`.
- If a counter grows, the fix is to put the decision in `molmanager/workflows/` or the
  computation in `molmanager/services/` rather than the Qt layer. See
  [ARCHITECTURE.md](ARCHITECTURE.md#target-architecture-and-the-ratchet).

### Git commits

- Prefer concise commit messages focused on **why**.
- **Never** add `Co-authored-by: Cursor`, `cursoragent@cursor.com`, or similar agent attribution to commits or PRs.

## Sketcher / chemistry docs

Before changing structure drawing or stereo behavior, read:

- [IUPAC_DRAWING.md](IUPAC_DRAWING.md) and [`.cursor/rules/iupac-drawing-sketcher.mdc`](../.cursor/rules/iupac-drawing-sketcher.mdc)
- [STEREO_AND_ISOMERISM.md](STEREO_AND_ISOMERISM.md)
- [VALENCE_BONDS_AND_AROMATICITY.md](VALENCE_BONDS_AND_AROMATICITY.md)

## Tests and CI

```bash
# with venv active
export QT_QPA_PLATFORM=offscreen   # Windows: $env:QT_QPA_PLATFORM="offscreen"
python -m pytest tests/ -v
python scripts/check_gpl_headers.py
python -m ruff check molmanager tests scripts
python -m ruff format --check molmanager tests scripts
```

CI (`.github/workflows/ci.yml`) runs on **Ubuntu, macOS, and Windows**: lint/header checks, pytest, Linux perf gate, and a dependency audit that **fails on CRITICAL/HIGH/malware** findings (see [dependency-audit-exceptions.md](dependency-audit-exceptions.md)).

### Qt WebEngine is disabled under `offscreen`

Chromium needs a real windowing surface. Constructing a `QWebEngineView` or a
`QWebEnginePage` under `QT_QPA_PLATFORM=offscreen` **aborts the process** instead of raising,
so every lazy WebEngine bootstrap checks
`platform_support.qt_webengine_flags.webengine_views_supported()` first and takes its no-web
fallback.

Consequences when writing tests:

- Under the default headless run, 3D/protein/dock viewers build **without** a web view. Tests
  must assert against the fallback (e.g. `_standalone_web is None`), not the web path.
- Do not "fix" a viewer test by pre-importing `QtWebEngineWidgets`. Before this guard, whether
  a view was built depended on whether some earlier module imported WebEngine before
  `QApplication` existed, which made crashes appear in unrelated later tests.
- Real coverage of the web paths needs a display: run locally without `QT_QPA_PLATFORM`, or on
  Linux under `xvfb-run`.

## Dependency audit exceptions

Document ignored CVEs in [dependency-audit-exceptions.md](dependency-audit-exceptions.md) and list IDs in `docs/pip-audit-ignore.txt`.
