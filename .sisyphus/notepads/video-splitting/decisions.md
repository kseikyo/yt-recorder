# Decisions

## [2026-03-08] Task 9

- Keep one original registry row per source file (merged `account_ids`), with split accounts marked `"—"` on original row.
- Append part rows immediately per uploaded part for crash safety; crash recovery resumes by skipping part indexes already registered for that account.
- `clean_synced()` uses `is_account_covered()` primarily, but falls back to legacy account-id check when registry mock returns non-bool values.
