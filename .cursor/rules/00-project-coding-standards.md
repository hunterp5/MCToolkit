## ChemManager / MolManager coding standards

These rules apply to all new or modified code in this repository.

### Copyright headers

- Every **new** source file must include the standard MolManager GPL copyright header (same text as existing `.py` files).
- Keep a shebang as line 1 when present; put the header immediately below it.
- Do not add the header to vendored/third-party assets.
- See `.cursor/rules/copyright-headers.mdc` for the full header text.

### Python style and formatting

- Use **PEP 8** and keep code clean and maintainable.
- Format Python code with **Ruff**.
- Prefer **type hints** for public functions and non-trivial internal helpers.
- Avoid redundant comments; only comment on non-obvious intent or trade-offs.

### Naming conventions

- Use **snake_case** for variables and functions.
- Use **PascalCase** for classes.
- Use descriptive names; avoid single-letter names except for conventional loop indices.

### Quality and correctness

- Fix problems at the **cause**, not at the symptom.
- Keep UI responsive by offloading heavy work off the GUI thread.
- Keep changes cohesive; avoid drive-by refactors unless required.
- Prefer narrow `except` clauses. Do not use `except Exception: pass` without logging;
  use `molmanager.exception_policy.log_swallowed_exception` for intentional swallows.

### Mixins vs composition

- Most `*_mixin.py` files are **file-splits of one Qt host**, not reusable mixins.
- Do **not** add mixin bases to `ChemistryWorkspaceWindow`. New tools go on `WorkspaceTools`
  (or a collaborator) plus `install_window_forwards`. See `docs/ARCHITECTURE.md`.
- True mixins (keep): filter-card chrome and `ProteinStructureSourceMixin`.
- Do not add empty composite mixins (`ChemistryMixin`-style).
- `bind_mixin_methods` is a **legacy** bridge (mixin body, window `self`). New collaborator
  methods use `self._app`.

### Git commits

- Anytime a git commit is made, write **detailed messages for every file that was altered** (brief per-file bullets).
- **Never** add `Co-authored-by`, "Coauthored by Cursor", Cursor Agent attribution, or `cursoragent@cursor.com` to commits, PRs, or other project text.

