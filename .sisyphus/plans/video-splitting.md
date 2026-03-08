# Video Splitting v2 — Per-Account Tiered Limit Detection

## TL;DR

> **Quick Summary**: Auto-detect each YouTube account's upload duration limit (full/1hr/15min) on first failure, persist it, and proactively split future uploads per-account using ffmpeg stream-copy. Different accounts may receive different splits of the same source video.
>
> **Deliverables**:
> - `VideoSplitter` adapter (ffprobe JSON + ffmpeg segment + keyframe-safe buffer)
> - `Config` with `YouTubeAccount.upload_limit_secs` field + tomlkit writer for limit persistence
> - `VideoTooLongError` with DOM-based detection (parallel polling, not 30-min timeout)
> - Registry v3: per-account part rows with parent linkage
> - RAID v2: per-account tiered upload strategy (full vs split based on learned limits)
> - Pipeline: tier detection loop, proactive splitting, per-account part registration, clean update
> - CLI: `reset-limits` command, ffmpeg/ffprobe health check
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 4 waves
> **Critical Path**: Task 1 → Task 7 → Task 9 → Task 10

---

## Context

### Original Request (v1)
Add ffmpeg splitting for videos exceeding YouTube duration limits. Track parts for reconstruction. Handle daily limit edge case.

### v2 Evolution
User requires **per-account limit detection**. Accounts may have different limits (full/1hr/15min). System should:
1. Try full video first (unknown accounts)
2. On rejection: try next tier down (55min → 14min)
3. Persist detected limit to config.toml
4. Proactively split on all future uploads for that account

### Research Findings (validated 2026-03-07)
- **YouTube rejects AFTER upload**: "Processing abandoned. Video is too long." — appears as red thumbnail in Studio, not as blocking dialog during upload
- **Detection point**: During `wait_for_function()` phase (Done button disabled). Must poll for error DOM elements in parallel — otherwise every failed attempt costs 30-min timeout
- **Keyframe drift**: `-f segment -c copy` splits at nearest keyframe, not exact time. 5-min buffer absorbs this
- **Failed uploads count toward daily quota**: Tiered fallback burns 1-3 quota slots per account on first detection
- **No config writer exists**: Only `load_config()` + template. Need `tomlkit` for comment-preserving writes
- **Codebase unchanged from v1**: All file references verified valid

### Metis Review (auto-resolved)
- **Detection speed**: Modified `wait_for_function` JS to poll for error elements AND Done button simultaneously. Return discriminated result: `{done: true}` vs `{error: "text"}` vs `null`
- **Config writer**: Use `tomlkit` (preserves comments/formatting). Add as dependency.
- **Upload order**: Per-account batching — all parts to Account A, then all to Account B. Sequential within account.
- **Transcript limitation**: Split primaries get per-part transcripts. No concatenation in this iteration (DEFERRED).
- **Account limit staleness**: Add `yt-recorder reset-limits` command. Limits can change (user verifies account later).
- **UploadTimeoutError vs VideoTooLongError ambiguity**: DOM-based detection resolves this. If timeout with NO error text → UploadTimeoutError (network). If error text found → VideoTooLongError (limit detected).
- **Partial recovery**: Parts with video_ids in registry → skip on next run. Unregistered parts → scanner picks them up.

---

## Work Objectives

### Core Objective
Auto-detect each account's YouTube upload duration limit, persist it, and proactively split future uploads per-account so different accounts receive optimally-sized files.

### Concrete Deliverables
- `src/yt_recorder/adapters/splitter.py` — `VideoSplitter` class
- `src/yt_recorder/domain/exceptions.py` — `VideoTooLongError`, `DailyLimitError`, `SplitterError`
- `src/yt_recorder/domain/models.py` — `RegistryEntry` + 3 optional fields, `YouTubeAccount` + `upload_limit_secs`
- `src/yt_recorder/config.py` — `upload_limit_secs` loading from TOML, `save_detected_limit()` via tomlkit write-back
- `src/yt_recorder/adapters/registry.py` — v3 schema with per-account part rows
- `src/yt_recorder/adapters/youtube.py` — description field + parallel error detection
- `src/yt_recorder/adapters/raid.py` — per-account tiered upload strategy
- `src/yt_recorder/pipeline.py` — tier detection, proactive splitting, per-account orchestration
- `src/yt_recorder/cli.py` — `reset-limits` command, ffmpeg/ffprobe health check
- `src/yt_recorder/constants.py` — description + error selectors
- Tests: `test_splitter.py`, `test_config_v2.py`, `test_registry_v3.py`, `test_pipeline_split.py`, `test_raid_tiered.py`

### Definition of Done
- [ ] `pytest --tb=short` → all green
- [ ] `mypy --strict src/` → exit 0
- [ ] `ruff check src/` → exit 0
- [ ] v2 config.toml (flat accounts) loads correctly via auto-migration
- [ ] Detected limit persists to config.toml and is used on subsequent uploads
- [ ] v2 registry.md loads correctly with new MarkdownRegistryStore

### Must Have
- Per-account upload limit detection (full → 55min → 14min tiers)
- Learned limits persisted to config.toml under each account
- VideoTooLongError detected via DOM polling (not 30-min timeout)
- Per-account splitting: Account A gets full video, Account B gets N parts
- Registry tracks per-account part rows with parent linkage
- Clean: original eligible only when ALL accounts covered (via full or all parts)
- ffmpeg/ffprobe health check
- `yt-recorder reset-limits` standalone CLI command

### Must NOT Have (Guardrails)
- NO auto-deletion of failed/rejected YouTube videos (user cleans manually)
- NO re-encoding during split (`-c copy` only)
- NO transcript concatenation for split primaries (DEFERRED)
- NO parallel uploads of split parts (sequential, avoid bot detection)
- NO smart/content-aware split points (duration-only)
- NO configurable tiers beyond 55min/14min
- NO description on non-split videos
- NO separate CLI commands for split management

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest + mypy + ruff)
- **Automated tests**: Tests-after (new test files for new modules)
- **Framework**: pytest

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — 6 parallel, no dependencies):
├── Task 1: VideoSplitter adapter (ffprobe JSON + ffmpeg segment) [unspecified-low]
├── Task 2: Config (YouTubeAccount.upload_limit_secs + tomlkit writer) [unspecified-high]
├── Task 3: Exceptions (VideoTooLongError + DailyLimitError + SplitterError) [quick]
├── Task 4: Registry v3 schema (per-account part columns) [unspecified-low]
├── Task 5: YouTube adapter (description + parallel error detection) [unspecified-high]
└── Task 6: Constants + Health check (selectors + ffmpeg/ffprobe) [quick]

Wave 2 (After Wave 1 — 2 parallel):
├── Task 7: RAID (description passthrough + per-account upload method) [unspecified-low]
└── Task 8: CLI reset-limits command [quick]

Wave 3 (After Wave 2 — 1 task):
└── Task 9: Pipeline orchestration (tier detection + proactive split + per-account registration + clean) [deep]

Wave 4 (After Wave 3 — 1 task):
└── Task 10: Integration tests + full suite verification [unspecified-high]

Wave FINAL (After Task 10 — 4 parallel):
├── Task F1: Plan compliance audit [oracle]
├── Task F2: Code quality review [unspecified-high]
├── Task F3: QA scenario execution [unspecified-high]
└── Task F4: Scope fidelity check [deep]

Critical Path: Task 1 → Task 7 → Task 9 → Task 10 → F1-F4
Parallel speedup: ~60% faster than sequential
Max concurrent: 6 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 7, 9 |
| 2 | — | 7, 8, 9 |
| 3 | — | 5, 7, 9 |
| 4 | — | 9 |
| 5 | 3 | 7, 9 |
| 6 | — | — |
| 7 | 2, 3, 5 | 9 |
| 8 | 2 | — |
| 9 | 1, 2, 4, 7 | 10 |
| 10 | 9 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 6 tasks — T1→`unspecified-low`, T2→`unspecified-high`, T3→`quick`, T4→`unspecified-low`, T5→`unspecified-high`, T6→`quick`
- **Wave 2**: 2 tasks — T7→`unspecified-low`, T8→`quick`
- **Wave 3**: 1 task — T9→`deep`
- **Wave 4**: 1 task — T10→`unspecified-high`
- **FINAL**: 4 tasks — F1→`oracle`, F2→`unspecified-high`, F3→`unspecified-high`, F4→`deep`

---

## TODOs

- [ ] 1. VideoSplitter Adapter

  **What to do**:
  - Create `src/yt_recorder/adapters/splitter.py`
  - Add `SplitterError(YTRecorderError)` to `src/yt_recorder/domain/exceptions.py`
  - Implement `VideoSplitter` class:
    - `get_duration(path: Path) -> float` — run ffprobe with `-of json -show_format -show_streams -select_streams v:0`, parse `format.duration` from JSON. Raise `SplitterError` if ffprobe not found or non-zero exit.
    - `get_metadata(path: Path) -> dict` — same ffprobe call, return `{duration, size_bytes, codec, width, height}` for description embedding.
    - `needs_split(path: Path, threshold_secs: float) -> bool` — compare duration to threshold.
    - `split(path: Path, threshold_secs: float) -> list[Path]` — if no split needed, return `[path]`. Create dot-prefixed temp dir `path.parent / f".{path.stem}_parts"`. Run `ffmpeg -i <path> -c copy -map 0 -segment_time <threshold> -f segment -reset_timestamps 1 <tempdir>/<stem>_part%03d<suffix>`. Return sorted output paths. Raise `SplitterError` on ffmpeg not found or non-zero exit. Warn (not raise) if `shutil.disk_usage` free < file_size × 1.1.
    - `cleanup_parts(parts: list[Path]) -> None` — delete temp part files and their parent dir if empty.
  - Tier constants: `TIER_1HR = 3300` (55 min), `TIER_15MIN = 840` (14 min) in splitter module.
  - Use `subprocess.run()` with `capture_output=True, text=True, timeout=` pattern.
  - Tests: `tests/test_splitter.py` — duration detection (mocked), needs_split boundary, split output list (mocked), ffmpeg-not-found, no-split returns [original], metadata parsing.

  **Must NOT do**:
  - No re-encoding (always `-c copy`)
  - Don't touch pipeline, registry, or config
  - No custom segment naming beyond `_part%03d`

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-6)
  - **Blocks**: Tasks 7, 9
  - **Blocked By**: None

  **References**:
  - `src/yt_recorder/domain/exceptions.py` — existing hierarchy, `YTRecorderError` base class
  - `src/yt_recorder/adapters/transcriber.py` — subprocess usage pattern in codebase
  - `tests/test_registry.py` — test structure and fixtures to follow
  - ffprobe JSON: `ffprobe -v error -of json -show_format -show_streams -select_streams v:0 <file>`
  - ffmpeg segment: `ffmpeg -i <input> -c copy -map 0 -segment_time <secs> -f segment -reset_timestamps 1 <output>`

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_splitter.py -v` → all green
  - [ ] `mypy --strict src/yt_recorder/adapters/splitter.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Duration detection returns float from JSON
    Tool: Bash (pytest)
    Steps:
      1. Mock subprocess.run to return JSON with format.duration="3661.5"
      2. Call VideoSplitter().get_duration(Path('fake.mp4'))
      3. Assert return == 3661.5
    Expected Result: 3661.5
    Evidence: .sisyphus/evidence/task-1-duration.txt

  Scenario: SplitterError on missing ffprobe
    Tool: Bash (pytest)
    Steps:
      1. Mock subprocess.run to raise FileNotFoundError
      2. Assert VideoSplitter().get_duration() raises SplitterError
    Expected Result: SplitterError raised
    Evidence: .sisyphus/evidence/task-1-no-ffprobe.txt
  ```

  **Commit**: YES — `feat(splitter): VideoSplitter with ffprobe JSON + ffmpeg stream-copy split`

- [ ] 2. Config v2: YouTubeAccount.upload_limit_secs + tomlkit Writer

  **What to do**:
  - Add `tomlkit` to project dependencies (`pyproject.toml`)
  - In `src/yt_recorder/domain/models.py`:
    - Add `upload_limit_secs: float | None = None` to `YouTubeAccount` frozen dataclass (line 76-79). Default None = unknown limit, try full first.
  - `Config.accounts` stays as `list[YouTubeAccount]` — NO type change. The new field is on YouTubeAccount itself.
  - **Config migration** in `src/yt_recorder/config.py` `load_config()` (lines 73-84):
    - Current format: `primary = "/path/to/state.json"` (flat string)
    - New format: `[accounts.primary]` with `path = "..."` and `upload_limit_secs = 3300`
    - Detect which format per-account (string vs dict):
      ```python
      for i, (name, value) in enumerate(data["accounts"].items()):
          if isinstance(value, str):
              # Old flat format
              account = YouTubeAccount(name=name, storage_state=Path(value),
                  cookies_path=Path(value).parent / f"{name}_cookies.txt",
                  role="primary" if i == 0 else "mirror")
          elif isinstance(value, dict):
              # New nested format
              account = YouTubeAccount(name=name, storage_state=Path(value["path"]),
                  cookies_path=Path(value["path"]).parent / f"{name}_cookies.txt",
                  role="primary" if i == 0 else "mirror",
                  upload_limit_secs=value.get("upload_limit_secs"))
      ```
  - **Config write-back**: Create `save_detected_limit(config_path: Path, account_name: str, limit_secs: float) -> None` in config.py:
    ```python
    import tomlkit
    def save_detected_limit(config_path: Path, account_name: str, limit_secs: float) -> None:
        doc = tomlkit.parse(config_path.read_text())
        account_value = doc["accounts"][account_name]
        if isinstance(account_value, str):
            # Migrate flat→nested inline
            table = tomlkit.table()
            table["path"] = account_value
            table["upload_limit_secs"] = limit_secs
            doc["accounts"][account_name] = table
        else:
            doc["accounts"][account_name]["upload_limit_secs"] = limit_secs
        config_path.write_text(tomlkit.dumps(doc))
    ```
  - **No call site changes needed** — `Config.accounts` is still `list[YouTubeAccount]`. All code accessing `.name`, `.storage_state`, `.cookies_path`, `.role` continues to work. New code reads `.upload_limit_secs` (optional, defaults to None).
  - Tests: `tests/test_config_v2.py` — flat format loads with None limit, nested format loads with limit, save_detected_limit round-trip, mixed format (some flat, some nested)

  **Must NOT do**:
  - Don't change `Config.accounts` type (stays `list[YouTubeAccount]`)
  - Don't change `YouTubeAccount` from frozen (create new instances via `dataclasses.replace()` if needed)
  - Don't change config template default format

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Config migration logic, tomlkit integration, round-trip preservation
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3-6)
  - **Blocks**: Tasks 7, 8, 9
  - **Blocked By**: None

  **References**:
  - `src/yt_recorder/domain/models.py:65-79` — `YouTubeAccount` frozen dataclass (add `upload_limit_secs` field)
  - `src/yt_recorder/config.py:11-28` — `Config` dataclass (accounts is `list[YouTubeAccount]`, DO NOT CHANGE TYPE)
  - `src/yt_recorder/config.py:73-84` — account parsing loop in `load_config()` (modify for format detection)
  - `src/yt_recorder/config.py:113-144` — `save_config_template()` (reference only)
  - `src/yt_recorder/adapters/raid.py:20-41` — `RaidAdapter.__init__` uses `YouTubeAccount.role`, `.name`
  - `src/yt_recorder/pipeline.py:26-62` — `from_directory()` builds YouTubeAccount objects
  - `pyproject.toml` — add `tomlkit` dependency

  **Acceptance Criteria**:
  - [ ] `python -c "from yt_recorder.domain.models import YouTubeAccount; from pathlib import Path; a = YouTubeAccount('test', Path('/tmp'), Path('/tmp/c'), 'primary'); assert a.upload_limit_secs is None; print('OK')"` → OK
  - [ ] Old flat config.toml loads without errors (backward compat)
  - [ ] `save_detected_limit()` writes and preserves existing config content
  - [ ] `pytest tests/test_config_v2.py -v` → all green
  - [ ] `mypy --strict src/yt_recorder/config.py src/yt_recorder/domain/models.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Flat config loads with None upload_limit_secs
    Tool: Bash (python -c)
    Steps:
      1. Write tmp config.toml with flat accounts (primary = "/path")
      2. load_config(tmp_path)
      3. Assert config.accounts[0].upload_limit_secs is None
      4. Assert config.accounts[0].storage_state == Path("/path")
    Expected Result: YouTubeAccount with path and None limit
    Evidence: .sisyphus/evidence/task-2-migration.txt

  Scenario: save_detected_limit persists and preserves comments
    Tool: Bash (python -c)
    Steps:
      1. Write tmp config.toml with comment "# my comment" and flat account
      2. save_detected_limit(path, "primary", 3300.0)
      3. Re-read file, assert "upload_limit_secs = 3300" present
      4. Assert "# my comment" still present
    Expected Result: Limit saved, comments preserved, flat→nested migration done
    Evidence: .sisyphus/evidence/task-2-save-limit.txt
  ```

  **Commit**: YES — `feat(config): YouTubeAccount.upload_limit_secs + tomlkit write-back`

- [ ] 3. Exceptions: VideoTooLongError + DailyLimitError + SplitterError

  **What to do**:
  - In `src/yt_recorder/domain/exceptions.py`, add:
    ```python
    class DailyLimitError(YouTubeError):
        """YouTube daily upload limit reached."""

    class VideoTooLongError(YouTubeError):
        """Video exceeds account's duration limit."""
        def __init__(self, message: str, detected_limit_secs: float | None = None) -> None:
            super().__init__(message)
            self.detected_limit_secs = detected_limit_secs

    class SplitterError(YTRecorderError):
        """ffmpeg/ffprobe operation failed."""
    ```
  - `VideoTooLongError` carries `detected_limit_secs` so the caller can persist the tier.

  **Must NOT do**:
  - Don't add exception handling logic here (that's Tasks 5, 7, 9)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4-6)
  - **Blocks**: Tasks 5, 7, 9
  - **Blocked By**: None

  **References**:
  - `src/yt_recorder/domain/exceptions.py:4-53` — existing hierarchy

  **Acceptance Criteria**:
  - [ ] `python -c "from yt_recorder.domain.exceptions import VideoTooLongError, DailyLimitError, SplitterError, YouTubeError, YTRecorderError; assert issubclass(VideoTooLongError, YouTubeError); assert issubclass(DailyLimitError, YouTubeError); assert issubclass(SplitterError, YTRecorderError); e = VideoTooLongError('too long', 3300); assert e.detected_limit_secs == 3300; print('OK')"` → OK
  - [ ] `mypy --strict src/yt_recorder/domain/exceptions.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Exception hierarchy correct
    Tool: Bash (python -c)
    Steps: Assert subclass relationships and detected_limit_secs attribute
    Expected Result: All assertions pass
    Evidence: .sisyphus/evidence/task-3-hierarchy.txt
  ```

  **Commit**: YES — `feat(exceptions): VideoTooLongError + DailyLimitError + SplitterError`

- [ ] 4. Registry v3 Schema: Per-Account Part Columns

  **What to do**:
  - In `src/yt_recorder/domain/models.py`:
    - Add to `RegistryEntry`: `part_index: int | None = None`, `total_parts: int | None = None`, `parent_file: str | None = None`
    - Defaults to None so ALL existing construction sites work unchanged
  - In `src/yt_recorder/adapters/registry.py`:
    - Bump `_REGISTRY_VERSION = 3`
    - `_format_table_header`: add `"Part"`, `"Total"`, `"Parent"` as LAST three columns (after dynamic account columns)
    - `_format_row`: append part fields (empty string if None)
    - `_parse_row`: after parsing account_ids, read indices `4 + len(account_names)` through `+2` — if not present (v2), default to None
    - All 6 `RegistryEntry(...)` construction sites: add part kwargs (defaulting to preserve existing values)
    - Add helper: `get_parts_for_parent(parent_file: str) -> list[RegistryEntry]` — returns all entries where `entry.parent_file == parent_file`
    - Add helper: `is_account_covered(file: str, account_name: str) -> bool`:
      - If entry for `file` has `account_ids[account_name] != "—"` → True (full video uploaded)
      - Else: check all parts with `parent_file == file` — if ALL have `account_ids[account_name] != "—"` → True
      - Else → False
  - Tests: `tests/test_registry_v3.py` — v2 compat, v3 round-trip, get_parts_for_parent, is_account_covered

  **Must NOT do**:
  - Don't put new columns between Transcript and accounts (column ordering matters)
  - Don't auto-migrate v2 files on load (read-only compat, write v3 on next save)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-3, 5-6)
  - **Blocks**: Task 9
  - **Blocked By**: None

  **References**:
  - `src/yt_recorder/adapters/registry.py:1-379` — full file; `_parse_row` positional indexing, `_format_row`, all `RegistryEntry(...)` construction sites (lines 147-153, 183-188, 201-210, 307-338)
  - `src/yt_recorder/domain/models.py:40-57` — current `RegistryEntry`
  - `src/yt_recorder/pipeline.py:137-145` — additional `RegistryEntry(...)` construction site

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_registry_v3.py -v` → all green
  - [ ] `pytest tests/test_registry.py -v` → still all green (no regression)
  - [ ] `mypy --strict src/yt_recorder/domain/models.py src/yt_recorder/adapters/registry.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: v2 registry loads with None for new columns
    Tool: Bash (pytest)
    Steps:
      1. Create v2 registry.md (no Part/Total/Parent cols)
      2. Load with MarkdownRegistryStore
      3. Assert all entries have part_index=None
    Expected Result: No parse error, new fields None
    Evidence: .sisyphus/evidence/task-4-v2-compat.txt

  Scenario: is_account_covered with per-account parts
    Tool: Bash (pytest)
    Steps:
      1. Create registry with: original (primary=abc, backup=—) + 2 parts (primary=—, backup=def/ghi)
      2. Assert is_account_covered("original.mp4", "primary") → True (direct video_id)
      3. Assert is_account_covered("original.mp4", "backup") → True (all parts covered)
    Expected Result: Both accounts covered
    Evidence: .sisyphus/evidence/task-4-covered.txt
  ```

  **Commit**: YES — `feat(registry): v3 schema with per-account part columns`

- [ ] 5. YouTube Adapter: Description Field + Parallel Error Detection

  **What to do**:
  - In `src/yt_recorder/constants.py`:
    - Add `DESCRIPTION_TEXTAREA = "#description-textarea #textbox"` — YouTube Studio upload dialog description input
    - Add `VIDEO_TOO_LONG_ERROR = "text=Video is too long"` — selector for too-long rejection (add TODO comment: may need tuning)
    - Add `DAILY_LIMIT_ERROR = "text=upload limit"` — selector for daily limit error (add TODO comment: verify exact wording)
  - In `src/yt_recorder/adapters/youtube.py`:
    - Update `upload()` signature: `upload(self, path: Path, title: str, description: str = "") -> UploadResult`
    - After title fill (line ~117): if `description`: fill description textarea
    - **Critical change to `wait_for_function()`** (lines 156-163): Replace with a JS function that polls for BOTH Done button AND error elements:
      ```python
      page.wait_for_function(
          """() => {
              const done = document.querySelector('#done-button');
              const tooLong = document.querySelector('[class*="error"]');
              const errorText = document.body?.innerText || '';
              if (errorText.includes('too long') || errorText.includes('Video is too long')) {
                  return { error: 'too_long' };
              }
              if (errorText.includes('upload limit') || errorText.includes('daily')) {
                  return { error: 'daily_limit' };
              }
              if (done && done.getAttribute('aria-disabled') !== 'true') {
                  return { done: true };
              }
              return null;
          }""",
          timeout=constants.UPLOAD_TIMEOUT_SECONDS * 1000,
      )
      ```
    - Parse return value: if `result.get("error") == "too_long"` → raise `VideoTooLongError`. If `"daily_limit"` → raise `DailyLimitError`. If `result.get("done")` → proceed normally. If timeout → `UploadTimeoutError`.
  - Update `src/yt_recorder/domain/protocols.py` — `VideoUploader.upload` signature: add `description: str = ""`
  - Tests: `tests/test_youtube_v2.py` — description fill, error detection returns discriminated result, VideoTooLongError raised, DailyLimitError raised

  **Must NOT do**:
  - Don't fill description on non-split uploads (description="" means skip)
  - Don't change existing error handling beyond adding parallel detection
  - Don't navigate away from upload dialog to check status (detection must happen in-dialog)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Playwright JS injection, careful DOM detection, protocol change
  - **Skills**: [`playwright`]
    - `playwright`: Understanding wait_for_function JS evaluation patterns

  **Parallelization**:
  - **Can Run In Parallel**: YES (but depends on Task 3 for exception imports)
  - **Parallel Group**: Wave 1 (with Tasks 1-4, 6) — start after Task 3 completes
  - **Blocks**: Tasks 7, 9
  - **Blocked By**: Task 3

  **References**:
  - `src/yt_recorder/adapters/youtube.py:88-192` — full upload method; description fill after line 117, error detection replaces lines 156-167
  - `src/yt_recorder/adapters/youtube.py:54-61` — `_check_bot_detection` / `_check_session_expired` patterns
  - `src/yt_recorder/constants.py` — existing selectors
  - `src/yt_recorder/domain/protocols.py` — `VideoUploader.upload` signature to update

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_youtube_v2.py -v` → all green
  - [ ] `mypy --strict src/yt_recorder/adapters/youtube.py src/yt_recorder/domain/protocols.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: wait_for_function detects "too long" error
    Tool: Bash (pytest)
    Steps:
      1. Mock page.wait_for_function to return {"error": "too_long"}
      2. Call adapter.upload(path, title)
      3. Assert raises VideoTooLongError
    Expected Result: VideoTooLongError raised (not UploadTimeoutError)
    Evidence: .sisyphus/evidence/task-5-too-long.txt

  Scenario: Description filled when non-empty
    Tool: Bash (pytest)
    Steps:
      1. Mock page with description textarea element
      2. Call adapter.upload(path, title, description="[Part 1/3]")
      3. Assert textarea.fill called with "[Part 1/3]"
    Expected Result: Description written
    Evidence: .sisyphus/evidence/task-5-description.txt
  ```

  **Commit**: YES — `feat(youtube): description field + parallel VideoTooLongError detection`

- [ ] 6. Constants + Health Check: ffmpeg/ffprobe

  **What to do**:
  - In `src/yt_recorder/cli.py` health command:
    - After existing checks (Chrome, yt-dlp), add ffmpeg/ffprobe checks using `shutil.which("ffmpeg")` and `shutil.which("ffprobe")`
    - Output: `"ffmpeg:  ✓ found at /path"` or `"ffmpeg:  ✗ not found  (required for video splitting — install: brew install ffmpeg)"`
    - Same for ffprobe
  - No other changes — constants for Task 5 are handled there.

  **Must NOT do**:
  - Don't add `--split-threshold` CLI flag
  - Don't change existing health checks

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/yt_recorder/cli.py` — health command function; locate where Chrome/yt-dlp checks are printed
  - Pattern: `shutil.which("ffmpeg")` returns path or None

  **Acceptance Criteria**:
  - [ ] `yt-recorder health 2>&1 | grep -i ffmpeg` → shows ffmpeg line
  - [ ] `mypy --strict src/yt_recorder/cli.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Health shows ffmpeg status
    Tool: Bash
    Steps:
      1. Run yt-recorder health 2>&1
      2. Assert output contains "ffmpeg"
    Expected Result: ffmpeg status line present
    Evidence: .sisyphus/evidence/task-6-health.txt
  ```

  **Commit**: YES — `feat(health): ffmpeg/ffprobe check`

- [ ] 7. RAID: Description Passthrough + Per-Account Upload Method

  **What to do**:
  - In `src/yt_recorder/adapters/raid.py`:
  - **Update existing `upload()` signature**: add `description: str = ""`, pass through to all `adapter.upload()` calls (primary line 93, mirror line 103).
  - **Add new `upload_to_account()` method** for pipeline's per-account splitting:
    ```python
    def upload_to_account(
        self, account_name: str, path: Path, title: str, description: str = ""
    ) -> UploadResult:
        """Upload to a specific account. Used by pipeline for per-account split parts.

        Raises VideoTooLongError, DailyLimitError on failure (caller handles).
        """
        adapter = self._adapters[account_name]
        return adapter.upload(path, title, description=description)

    def assign_playlist_to_account(
        self, account_name: str, video_id: str, playlist: str
    ) -> bool:
        """Assign playlist on specific account."""
        adapter = self._adapters[account_name]
        return adapter.assign_playlist(video_id, playlist)
    ```
  - **DailyLimitError handling in existing `upload()`**: Catch `DailyLimitError` specifically for mirrors — log and set None (same as other failures). For primary: let it propagate (pipeline handles batch stop).
  - **VideoTooLongError handling in existing `upload()`**: Let it propagate for BOTH primary and mirrors. Pipeline handles tier detection.
  - Existing `upload()` return type stays: `tuple[dict[str, UploadResult | None], int]`. NO change.
  - Tests: `tests/test_raid_v2.py` — description passthrough, upload_to_account, VideoTooLongError propagates, DailyLimitError mirror=None/primary=propagate

  **Must NOT do**:
  - Don't put splitting logic in RAID (that's pipeline's job — Task 9)
  - Don't change existing return type
  - Don't import VideoSplitter in raid.py

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: Straightforward method additions, no complex logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (parallel with Task 8)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Tasks 3, 5

  **References**:
  - `src/yt_recorder/adapters/raid.py:74-113` — current `upload()` method (add description param, error handling)
  - `src/yt_recorder/adapters/raid.py:56-72` — `get_adapter()` pattern (reference for `upload_to_account`)
  - `src/yt_recorder/adapters/youtube.py` — (Task 5) updated upload signature with description

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_raid_v2.py -v` → all green
  - [ ] `mypy --strict src/yt_recorder/adapters/raid.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Description passed to primary and mirrors
    Tool: Bash (pytest)
    Steps:
      1. Mock adapters, call raid.upload(path, title, playlist, description="[Part 1/3]")
      2. Assert primary adapter.upload called with description="[Part 1/3]"
      3. Assert mirror adapter.upload called with description="[Part 1/3]"
    Expected Result: Description forwarded to all accounts
    Evidence: .sisyphus/evidence/task-7-description.txt

  Scenario: upload_to_account returns UploadResult directly
    Tool: Bash (pytest)
    Steps:
      1. Mock adapter for "backup" account
      2. Call raid.upload_to_account("backup", path, title, description="test")
      3. Assert returns UploadResult from that adapter
    Expected Result: Single UploadResult
    Evidence: .sisyphus/evidence/task-7-per-account.txt

  Scenario: VideoTooLongError propagates from primary
    Tool: Bash (pytest)
    Steps:
      1. Mock primary adapter.upload raises VideoTooLongError
      2. Call raid.upload()
      3. Assert VideoTooLongError propagates (not caught)
    Expected Result: Exception propagates to caller
    Evidence: .sisyphus/evidence/task-7-too-long-propagate.txt
  ```

  **Commit**: YES — `feat(raid): description passthrough + per-account upload method`

- [ ] 8. CLI: reset-limits Command

  **What to do**:
  - Add standalone `yt-recorder reset-limits` click command
  - When invoked: for each account in config, set `upload_limit_secs = None` via tomlkit
  - Output: `"Reset upload limits for N accounts. Next upload will re-detect."`
  - Use case: user verifies a previously unverified account, cached 840s limit is now wrong

  **Must NOT do**:
  - Don't reset other config values
  - Don't add per-account reset (reset all or nothing — simpler)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (parallel with Task 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: Task 2

  **References**:
  - `src/yt_recorder/cli.py` — existing command structure
  - `src/yt_recorder/config.py` — (Task 2) save_detected_limit, tomlkit usage

  **Acceptance Criteria**:
  - [ ] `yt-recorder reset-limits` → output shows reset count
  - [ ] Config file no longer has `upload_limit_secs` entries after reset

  **QA Scenarios**:
  ```
  Scenario: Reset clears all cached limits
    Tool: Bash
    Steps:
      1. Set upload_limit_secs=3300 in config for an account
      2. Run yt-recorder reset-limits
      3. Reload config, assert upload_limit_secs is None
    Expected Result: Limits cleared
    Evidence: .sisyphus/evidence/task-8-reset.txt
  ```

  **Commit**: YES — `feat(cli): reset-limits command`

- [ ] 9. Pipeline Orchestration: Tier Detection + Proactive Split + Per-Account Registration + Clean

  **What to do**:
  - This is the integration task. In `src/yt_recorder/pipeline.py`:

  **A. Per-account upload orchestration** (pipeline owns splitting logic, RAID provides per-account upload):
  - Import `VideoSplitter`, `TIER_1HR`, `TIER_15MIN` from splitter module
  - Before upload loop: `splitter = VideoSplitter()`
  - For each file, for each account:
    ```python
    duration = splitter.get_duration(path)
    account = config.accounts[i]  # YouTubeAccount with upload_limit_secs

    if account.upload_limit_secs and duration > account.upload_limit_secs:
        # Known limited — proactive split
        parts = splitter.split(path, account.upload_limit_secs)
        _upload_parts_to_account(raid, account, parts, title, playlist, path, directory)
    else:
        # Unknown or under limit — try full
        try:
            result = raid.upload_to_account(account.name, path, title)
            raid.assign_playlist_to_account(account.name, result.video_id, playlist)
            # Register full video for this account
        except VideoTooLongError:
            # Tier detection
            detected_limit = _detect_tier(raid, splitter, account, path, title, playlist, directory)
            save_detected_limit(config_path, account.name, detected_limit)
    ```
  - **`_detect_tier()` helper**: Try TIER_1HR first, upload first part only. If succeeds → limit=3300, upload rest. If fails → try TIER_15MIN, upload all. If both fail → log error, skip account.
  - **`_upload_parts_to_account()` helper**: For each part, call `raid.upload_to_account()`, register part entry immediately, assign playlist. Generate title `f"{base} [Part {i}/{n}]"` (truncate base to 100 chars). Generate description with reassembly metadata.

  **B. Registration of per-account results**:
  - Full video: register with `account_ids={this_acc: video_id, others: existing_or_dash}`
  - Parts: register sentinel for original (all split accounts get `"—"`), then per-part entries with `part_index`, `total_parts`, `parent_file`
  - Each account's video_ids go in their respective column. An account either has a video_id on the original row OR on all part rows, never both.
  - Register each entry immediately after upload (crash-safe)

  **C. DailyLimitError handling**:
  - Catch `DailyLimitError` from `raid.upload_to_account()`: log warning, `break` upload loop (stop all accounts, all files)

  **D. Clean update**:
  - Modify `clean_synced()` to use `registry.is_account_covered(file, account)` (Task 4 helper)
  - Original eligible when ALL accounts covered (via full or all parts)
  - Part temp files cleaned by splitter after all parts uploaded to all accounts

  **E. Crash recovery (NOT via scanner)**:
  - Scanner skips dot-prefixed dirs (scanner.py:64), so `.{stem}_parts` dirs are invisible to it. Recovery does NOT rely on scanner.
  - Instead: before splitting a file, check if `.{stem}_parts` dir already exists (from a crashed previous run). If yes:
    - List existing part files in the dir
    - Check which parts already have registry entries (uploaded before crash)
    - Upload only the missing parts (skip re-splitting — parts exist on disk)
  - If dir does NOT exist: split normally.
  - Crash mid-batch → temp parts persist → next run detects them → resumes.

  - Tests: `tests/test_pipeline_split.py` — split produces sentinel + parts, DailyLimitError stops loop, per-account different part counts, clean checks is_account_covered, non-split unchanged, crash recovery from existing temp dir

  **Must NOT do**:
  - Don't change non-split upload behavior
  - Don't batch-register (each entry immediately)
  - Don't delete original before all accounts are covered
  - Don't add retry logic for daily limit

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex orchestration integrating all previous tasks
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (solo)
  - **Blocks**: Task 10
  - **Blocked By**: Tasks 1, 2, 4, 7

  **References**:
  - `src/yt_recorder/pipeline.py:64-212` — `upload_new()` method (main integration point)
  - `src/yt_recorder/pipeline.py:414-459` — `clean_synced()` (update eligibility logic)
  - `src/yt_recorder/adapters/splitter.py` — (Task 1) VideoSplitter API
  - `src/yt_recorder/adapters/raid.py` — (Task 7) `upload_to_account()` and `assign_playlist_to_account()` methods
  - `src/yt_recorder/adapters/registry.py` — (Task 4) `is_account_covered()`, `get_parts_for_parent()`

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_pipeline_split.py -v` → all green
  - [ ] `pytest tests/ -v` → full suite green
  - [ ] `mypy --strict src/yt_recorder/pipeline.py` → no errors

  **QA Scenarios**:
  ```
  Scenario: Per-account split produces correct registry entries
    Tool: Bash (pytest)
    Preconditions: primary=no limit, backup=3300s limit, video=7200s
    Steps:
      1. Mock RAID: primary uploads full video, backup uploads 3 parts
      2. Run pipeline.upload_new()
      3. Assert: 1 entry for original (primary=abc, backup=—)
      4. Assert: 3 part entries (primary=—, backup=def/ghi/jkl)
    Expected Result: 4 registry entries with correct per-account mapping
    Evidence: .sisyphus/evidence/task-9-per-account.txt

  Scenario: Clean checks is_account_covered
    Tool: Bash (pytest)
    Steps:
      1. Set up registry: original (primary=abc, backup=—) + 2/3 parts for backup uploaded
      2. Assert clean NOT eligible (backup not fully covered)
      3. Add 3rd part for backup
      4. Assert clean IS eligible
    Expected Result: Clean waits for all parts
    Evidence: .sisyphus/evidence/task-9-clean.txt
  ```

  **Commit**: YES — `feat(pipeline): tier detection, proactive split, per-account orchestration, clean update`

- [ ] 10. Integration Tests + Full Suite Verification

  **What to do**:
  - Run `mypy --strict src/` — fix remaining type errors
  - Run `ruff check src/` — fix linting
  - Run `pytest --tb=short` — ensure all tests pass
  - Write `tests/test_integration_split.py`:
    - Scenario A: 2-hour video, primary (no limit) + backup (learned 3300s limit) → primary: 1 full upload, backup: 3 parts
    - Scenario B: Unknown account, full upload fails → tier detection → limit saved → next upload proactively splits
    - Scenario C: DailyLimitError after part 2 of 4 → parts 1-2 registered, 3-4 not → re-run picks up remaining
    - Scenario D: v2 config.toml (flat accounts) → loads correctly → save_detected_limit → re-loads with upload_limit_secs on YouTubeAccount
    - Scenario E: v2 registry.md → loads with None part fields → write back v3 → re-loads correctly
  - Verify `yt-recorder health` includes ffmpeg check
  - Verify `yt-recorder reset-limits` command clears cached limits

  **Must NOT do**:
  - Don't add new features
  - Don't change test structure of existing tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (solo)
  - **Blocks**: Final verification wave
  - **Blocked By**: Task 9

  **References**:
  - `tests/` — all existing test files for patterns
  - All files modified by Tasks 1-9

  **Acceptance Criteria**:
  - [ ] `pytest --tb=short` → 0 failures
  - [ ] `mypy --strict src/` → Success
  - [ ] `ruff check src/` → All checks passed
  - [ ] `pytest tests/test_integration_split.py -v` → all green

  **QA Scenarios**:
  ```
  Scenario: Full suite passes
    Tool: Bash
    Steps: pytest --tb=short && mypy --strict src/ && ruff check src/
    Expected Result: All pass
    Evidence: .sisyphus/evidence/task-10-suite.txt

  Scenario: Config migration integration
    Tool: Bash (python -c)
    Steps:
      1. Create flat config → load → assert YouTubeAccount has upload_limit_secs=None
      2. save_detected_limit → reload → assert limit present
    Expected Result: Full round-trip works
    Evidence: .sisyphus/evidence/task-10-config-roundtrip.txt
  ```

  **Commit**: YES — `test: integration tests for tiered split, per-account upload, config persistence`

---

## Final Verification Wave

> Run AFTER all TODOs complete. All must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`

  **What to do**:
  Systematically verify every Must Have and Must NOT Have item from the plan against the implemented codebase.

  **QA Scenarios**:

  ```
  Scenario: Must Have — Per-account upload limit detection
    Tool: Bash
    Steps:
      1. grep -r "upload_limit_secs" src/yt_recorder/ --include="*.py" -l
      2. grep -r "VideoTooLongError" src/yt_recorder/ --include="*.py" -l
      3. grep -rn "TIER_1HR\|TIER_15MIN\|3300\|840" src/yt_recorder/adapters/splitter.py
      4. grep -rn "TIER_1HR\|TIER_15MIN\|from.*splitter.*import" src/yt_recorder/pipeline.py
    Expected Result: upload_limit_secs in models.py + config.py; VideoTooLongError in exceptions.py + youtube.py + pipeline.py; tier constants defined in splitter.py (3300, 840); pipeline.py imports them from splitter
    Evidence: .sisyphus/evidence/f1-must-have-tiers.txt

  Scenario: Must Have — Learned limits persisted to config.toml
    Tool: Bash
    Steps:
      1. grep -n "tomlkit\|upload_limit" src/yt_recorder/config.py
      2. grep -n "save.*limit\|persist.*limit\|write.*config" src/yt_recorder/pipeline.py
    Expected Result: tomlkit import in config.py; save/persist function that writes upload_limit_secs back to TOML
    Evidence: .sisyphus/evidence/f1-must-have-persist.txt

  Scenario: Must Have — DOM-based VideoTooLongError detection
    Tool: Bash
    Steps:
      1. grep -n "too.long\|Processing abandoned\|video_too_long" src/yt_recorder/constants.py src/yt_recorder/adapters/youtube.py
      2. Verify detection is inside wait_for_function or its JS, NOT a separate 30-min timeout
    Expected Result: Error selector in constants.py; DOM polling logic in youtube.py wait_for_function
    Evidence: .sisyphus/evidence/f1-must-have-dom-detect.txt

  Scenario: Must Have — Per-account splitting
    Tool: Bash
    Steps:
      1. grep -n "split.*account\|per.account\|account.*parts" src/yt_recorder/pipeline.py
      2. Verify different accounts can get different split sizes (not global min)
    Expected Result: Pipeline logic that checks each account's limit and splits independently
    Evidence: .sisyphus/evidence/f1-must-have-per-account.txt

  Scenario: Must Have — Registry per-account part tracking
    Tool: Bash
    Steps:
      1. grep -n "part_index\|total_parts\|parent_file" src/yt_recorder/domain/models.py
      2. grep -n "_REGISTRY_VERSION.*=.*3" src/yt_recorder/adapters/registry.py
    Expected Result: part_index, total_parts, parent_file fields on RegistryEntry; version bumped to 3
    Evidence: .sisyphus/evidence/f1-must-have-registry.txt

  Scenario: Must Have — ffmpeg health check + reset-limits command
    Tool: Bash
    Steps:
      1. grep -n "ffmpeg\|ffprobe" src/yt_recorder/cli.py
      2. grep -n "reset.limits\|reset_limits" src/yt_recorder/cli.py
    Expected Result: health command checks ffmpeg/ffprobe; reset-limits standalone command exists
    Evidence: .sisyphus/evidence/f1-must-have-health-cli.txt

  Scenario: Must NOT Have — No forbidden patterns
    Tool: Bash
    Steps:
      1. grep -rn "os.remove\|os.unlink\|Path.unlink" src/yt_recorder/adapters/youtube.py — must NOT find auto-deletion of failed uploads
      2. grep -rn "\-c:v\|libx264\|libx265\|reencode\|re.encode" src/yt_recorder/ --include="*.py" — must NOT find re-encoding
      3. grep -rn "transcript.*concat\|merge.*transcript" src/yt_recorder/ --include="*.py" — must NOT find transcript concatenation
      4. grep -rn "asyncio\|gather\|parallel.*upload\|concurrent.*upload" src/yt_recorder/ --include="*.py" — must NOT find parallel uploads of parts
      5. grep -rn "description" src/yt_recorder/pipeline.py — verify description only set for split videos, not originals
    Expected Result: Zero matches for items 1-4; description usage only in split-upload context
    Failure Indicators: Any grep match for forbidden patterns = REJECT
    Evidence: .sisyphus/evidence/f1-must-not-have.txt
  ```

  Output: `Must Have [8/8] | Must NOT Have [5/5] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality** — `unspecified-high`

  **What to do**:
  Run all static analysis tools and review changed files for code quality issues.

  **QA Scenarios**:

  ```
  Scenario: Static analysis passes
    Tool: Bash
    Steps:
      1. mypy --strict src/yt_recorder/ 2>&1 | tee .sisyphus/evidence/f2-mypy.txt
      2. ruff check src/ 2>&1 | tee .sisyphus/evidence/f2-ruff.txt
      3. pytest --tb=short 2>&1 | tee .sisyphus/evidence/f2-pytest.txt
    Expected Result: mypy exits 0 ("Success"); ruff exits 0 ("All checks passed"); pytest exits 0 (all pass, 0 failures)
    Failure Indicators: Any tool exits non-zero = REJECT
    Evidence: .sisyphus/evidence/f2-mypy.txt, .sisyphus/evidence/f2-ruff.txt, .sisyphus/evidence/f2-pytest.txt

  Scenario: No code quality anti-patterns in changed files
    Tool: Bash
    Steps:
      1. git diff --name-only HEAD~10 -- src/ | xargs grep -n "# type: ignore\|as Any\|@no_type_check" || true
      2. git diff --name-only HEAD~10 -- src/ | xargs grep -n "except:$\|except Exception:$" || true
      3. git diff --name-only HEAD~10 -- src/ | xargs grep -n "print(" || true
      4. git diff --name-only HEAD~10 -- src/ | xargs grep -n "TODO\|FIXME\|HACK\|XXX" || true
    Expected Result: Zero matches for bare type ignores, bare excepts, print() in production code, stale TODOs
    Failure Indicators: Any match (except intentional, documented exceptions) = flag for review
    Evidence: .sisyphus/evidence/f2-antipatterns.txt
  ```

  Output: `mypy [PASS/FAIL] | ruff [PASS/FAIL] | pytest [N pass/N fail] | Anti-patterns [CLEAN/N issues] | VERDICT`

- [ ] F3. **QA Scenario Execution** — `unspecified-high`

  **What to do**:
  Re-execute ALL QA scenarios from Tasks 1-10. Capture fresh evidence from a clean state.

  **QA Scenarios**:

  ```
  Scenario: Re-run all task QA scenarios end-to-end
    Tool: Bash
    Steps:
      1. Create clean temp directory with test video files (use ffmpeg to generate 2-hour test video: ffmpeg -f lavfi -i testsrc=duration=7200:size=320x240:rate=1 -c:v libx264 -preset ultrafast -t 7200 /tmp/yt-test/test_2h.mp4)
      2. Run VideoSplitter scenarios from Task 1: split at 55min, split at 14min, verify no re-encoding (-c copy in ffprobe output)
      3. Run config persistence scenarios from Task 2: write limit, reload, verify value
      4. Run exception hierarchy from Task 3: instantiate each, verify inheritance
      5. Run registry v3 scenarios from Task 4: write part rows, read back, verify fields
      6. Run YouTube adapter scenarios from Task 5: verify description param accepted
      7. Run health check from Task 6: yt-recorder health shows ffmpeg line
      8. Run RAID scenarios from Task 7: verify per-account upload method exists
      9. Run CLI scenarios from Task 8: yt-recorder reset-limits (verify command exists and runs)
      10. Run pipeline scenarios from Task 9: verify tier detection logic with mock accounts
      11. Run integration test suite from Task 10: pytest tests/ -v
    Expected Result: All scenarios pass, evidence captured per-task
    Failure Indicators: Any scenario fails = REJECT with specific task number
    Evidence: .sisyphus/evidence/f3-scenario-{task-N}.txt for each task

  Scenario: Cross-task integration — split + upload + register + clean cycle
    Tool: Bash
    Steps:
      1. Create test config with 2 accounts (one with upload_limit_secs=3300, one with None)
      2. Run pipeline.upload_new() with a 2-hour test video (mocked YouTube adapter)
      3. Verify: account with limit=3300 gets split parts registered; account with None gets full video attempt
      4. Verify: registry shows correct part_index, total_parts, parent_file for split account
      5. Verify: clean logic checks ALL accounts have coverage before marking eligible
    Expected Result: Per-account behavior diverges correctly; registry accurate; clean safe
    Evidence: .sisyphus/evidence/f3-integration-cycle.txt
  ```

  Output: `Scenarios [N/N pass] | Integration [PASS/FAIL] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`

  **What to do**:
  Compare every task's spec against its actual implementation diff. Verify nothing was missed, nothing extra was added.

  **QA Scenarios**:

  ```
  Scenario: Task-by-task spec-vs-diff audit
    Tool: Bash
    Steps:
      1. For each commit in the commit strategy (10 commits), run: git log --oneline --all | grep "feat(splitter)\|feat(config)\|feat(exceptions)\|feat(registry)\|feat(youtube)\|feat(health)\|feat(raid)\|feat(cli)\|feat(pipeline)\|test:"
      2. For each commit, run git diff <commit>^..<commit> --stat to list changed files
      3. Compare changed files against the plan's task file lists — flag any file NOT in the task spec (scope creep) or any file IN the spec but NOT changed (missing work)
      4. For each task's "Must NOT do" items, verify the diff contains none of those patterns
    Expected Result: 1:1 mapping between spec and diff for all 10 tasks; zero scope creep; zero missing deliverables
    Failure Indicators: Unaccounted file changes, missing spec items, cross-task file contamination
    Evidence: .sisyphus/evidence/f4-scope-audit.txt

  Scenario: Cross-task contamination check
    Tool: Bash
    Steps:
      1. For each commit, list files changed
      2. Check if any file appears in a commit it shouldn't (e.g., pipeline.py changed in Task 1's commit)
      3. Flag any file touched by 2+ task commits that isn't explicitly shared (models.py, __init__.py are expected shared)
    Expected Result: Each task's commit touches only its designated files; shared files (models.py, exceptions.py) touched only by their designated tasks
    Failure Indicators: Unexpected file in wrong task's commit = contamination
    Evidence: .sisyphus/evidence/f4-contamination.txt
  ```

  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- `feat(splitter): VideoSplitter with ffprobe JSON + ffmpeg stream-copy split` — Task 1
- `feat(config): YouTubeAccount.upload_limit_secs + tomlkit write-back` — Task 2
- `feat(exceptions): VideoTooLongError + DailyLimitError + SplitterError` — Task 3
- `feat(registry): v3 schema with per-account part columns` — Task 4
- `feat(youtube): description field + parallel VideoTooLongError detection` — Task 5
- `feat(health): ffmpeg/ffprobe check + error selectors` — Task 6
- `feat(raid): description passthrough + per-account upload method` — Task 7
- `feat(cli): reset-limits command` — Task 8
- `feat(pipeline): tier detection, proactive split, per-account orchestration, clean update` — Task 9
- `test: integration tests for tiered split, per-account upload, config persistence` — Task 10

---

## Success Criteria

```bash
# All tests pass
pytest --tb=short
# Expected: no failures

# Type checking
mypy --strict src/yt_recorder/
# Expected: Success

# Linting
ruff check src/
# Expected: All checks passed

# Config loads with new field defaulting to None
python -c "
from yt_recorder.config import load_config
config = load_config()
for acct in config.accounts:
    assert hasattr(acct, 'upload_limit_secs'), f'{acct.name} missing upload_limit_secs'
    assert acct.upload_limit_secs is None, f'{acct.name} should default to None'
print(f'config OK: {len(config.accounts)} accounts, all upload_limit_secs=None')
"

# Health shows ffmpeg
yt-recorder health 2>&1 | grep -i ffmpeg
# Expected: ffmpeg status line
```

## Non-Obvious Design Decisions

### Why "learn once" instead of always-proactive
Proactive splitting for accounts with no limit wastes YouTube upload quota (1 video becomes N parts). Learning the limit on first failure (1-2 wasted uploads) then splitting proactively forever after is the optimal quota strategy.

### Why DOM-based error detection, not timeout-based
A 30-minute timeout per failed tier attempt means initial detection could take 90+ minutes (3 tiers × 30 min). Polling for error DOM elements in the wait_for_function JS catches the rejection in seconds.

### Why per-account splitting (not global minimum)
Taking `min(all_account_limits)` means verified accounts get unnecessarily small splits. Per-account splitting ensures each account gets optimally-sized files — full video where possible, splits only where needed.

### Why tomlkit over tomli_w
`tomli_w` writes but strips comments. The user's config.toml may have hand-written comments explaining settings. `tomlkit` preserves comments, formatting, and ordering during partial updates.

### Why no transcript concatenation
Each YouTube video part gets its own auto-generated transcript. Concatenating them requires timestamp alignment and overlap handling — a separate feature. Per-part transcripts work fine for search/reference.
