# Dependency audit exceptions

CI runs [`scripts/check_dependency_audit.py`](../scripts/check_dependency_audit.py)
after installing dependencies on Linux. That wrapper:

- Audits the **installed environment** with `pip-audit` (JSON).
- Skips IDs listed in [`pip-audit-ignore.txt`](pip-audit-ignore.txt).
- **Fails** on remaining malware (`MAL-*`) or advisories with severity CRITICAL/HIGH
  when severity metadata is present.
- Prints other findings as warnings (no CI failure) so non-critical noise does not
  block merges while still remaining visible in logs.

Add an ignore entry only when:

1. There is no fixed release yet, or upgrading breaks MCtoolkit, **and**
2. The risk is accepted for our single-user desktop usage model.

Document each ignored ID below.

## Current exceptions

_None._
