# Issues

## [2026-03-08] Task 9

- No blocker in code changes; had transient LSP/mypy mismatch on Optional narrowing for `account_limit`, fixed with explicit `assert account_limit is not None` before split calls.
