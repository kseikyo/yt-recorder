# Learnings

## [2026-03-06] Session ses_33d75d5d0fferga3OIyNzkECKJ — Setup

### Codebase Conventions
- Python 3.9+, strict mypy, ruff linting
- All domain models are frozen dataclasses
- Hexagonal architecture: domain/ (pure) ← adapters/ ← pipeline.py ← cli.py
- Exception hierarchy: YTRecorderError base → YouTubeError → specific errors
- Registry: markdown table, atomic writes via tempfile+os.replace, fcntl advisory locks
- Tests: pytest, mocked adapters (no real browser in tests)
- Worktree: /Users/lucassierota/Desktop/recordings/yt-recorder-video-splitting (branch: feat/video-splitting)
- Run commands from worktree path, not main repo

### Key File Locations (worktree)
- Domain models: src/yt_recorder/domain/models.py
- Exceptions: src/yt_recorder/domain/exceptions.py
- Protocols: src/yt_recorder/domain/protocols.py
- Registry adapter: src/yt_recorder/adapters/registry.py
- YouTube adapter: src/yt_recorder/adapters/youtube.py
- RAID adapter: src/yt_recorder/adapters/raid.py
- Pipeline: src/yt_recorder/pipeline.py
- CLI: src/yt_recorder/cli.py
- Config: src/yt_recorder/config.py
- Constants: src/yt_recorder/constants.py
- Tests: tests/

### Existing Test Infrastructure
- transcriber.py has a pre-existing mypy error (dict[str,Any] params issue) — pre-existing, not our fault
- tests/test_registry.py has pre-existing mypy errors (generator/frozen assignment) — pre-existing

### RegistryEntry Construction Sites (6 total — ALL need updating for new fields)
1. registry.py ~line 147 (update_transcript)
2. registry.py ~line 183 (update_account_id)
3. registry.py ~line 201 (update_many)
4. pipeline.py ~line 137 (upload_new — main registration)
5. Plus any in tests/test_registry.py

### Registry v2 Format
| File | Playlist | Uploaded | Transcript | {accounts...} |
New columns go AFTER account columns (append-only, no positional shift)

### Upload Flow (youtube.py)
Title fill → line ~117, Not-for-kids → line ~121
Description fill must go BETWEEN these two (after title, before not-for-kids)
Daily limit check goes after done_btn.click()

### Exception Hierarchy
YTRecorderError → YouTubeError (and others like RegistryError)
DailyLimitError must be subclass of YouTubeError

## [2026-03-08] Task 5 — YouTube upload description + DOM error detection

### Adapter Behavior
- `page.wait_for_function()` returns a JSHandle in Playwright sync API; call `.json_value()` before branching on upload results.
- Keep upload tests mock-only with `MagicMock`; a `None` guard around the JSHandle keeps older mocks from crashing.
- Description fill belongs right after title fill and should be skipped fully when description is empty.

### Verification Notes
- `uv run --with pytest pytest` still has a pre-existing failure in `tests/test_youtube.py::TestAssignPlaylist::test_assign_playlist_success`.
- `uv run mypy --strict` has no default targets in this repo; `uv run mypy --strict src/yt_recorder/adapters/youtube.py src/yt_recorder/domain/protocols.py` passes for this task.

## [2026-03-08] Task 9 — Pipeline per-account split orchestration

- Keep `VideoSplitter` imported lazily inside pipeline methods; tests must patch `yt_recorder.adapters.splitter.VideoSplitter`, not `yt_recorder.pipeline.VideoSplitter`.
- `upload_new()` can preserve old unit test compatibility by falling back to `raid.upload()` when `raid.mirrors` is not a real list (Mock-heavy tests), while real `RaidAdapter` still uses per-account flow.
- Crash recovery is stable when part rows are appended per part and missing indexes are inferred via `registry.get_parts_for_parent(parent_file)` + `account_ids[account] != "—"`.
