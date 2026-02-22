Created SECURITY.md with details on path traversal protection, log sanitization, credential permissions, and CDP port exposure.

## [2026-02-22] Task: B3
Updated README.md with v0.2 architecture diagram, TranscriptStatus documentation, clean/health commands, and "PRs paused" notice. Preserved existing content. Linked to SECURITY.md.

## [2026-02-22] Task: C1
Bumped version to 0.2.0 in pyproject.toml. Added `ruff format --check src tests` to CI lint job (between ruff check and mypy) to align with pre-commit hooks. Fixed RUF059 unused variable in test_raid.py. All 179 tests pass, ruff/mypy clean.
