# Learnings — youtube-selector-fix

## [2026-02-23T03:10:42.218Z] Session Start
Session: ses_37785b3f2ffeIGuaPiimWtWMf3
Plan initialized.

## [2026-02-23] Task 1: Live DOM Inspection Complete

### Upload flow selectors — mostly UNCHANGED
- `input[type="file"]`, `#title-textarea #textbox`, `#next-button`, `#done-button` all still work
- `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` still works (old tp-yt- prefix)
- `span.video-url-fadeable a` still works (href empty during processing)
- `#done-button` text changed from "Done" to "Save" — ID unchanged

### Dialog scrim: `tp-yt-iron-overlay-backdrop`
- Tag: TP-YT-IRON-OVERLAY-BACKDROP, display:block, zIndex:1
- Multiple instances (3) on upload page — must target correct one

### Playlist flow — BREAKING CHANGES
- OLD: `tp-yt-paper-button[aria-label*="Playlist"]` → DEAD
- NEW trigger: `ytcp-video-metadata-playlists ytcp-dropdown-trigger[aria-label="Select playlists"]`
- Opens dialog: `tp-yt-paper-dialog.ytcp-playlist-dialog` (aria-label="Choose playlists")
- Search: `#search-input` (YTCP-SEARCH-BAR), hidden when 0 playlists
- Items: `tp-yt-paper-checkbox` inside `div#items` (NOT tp-yt-paper-item)
- Close dialog: `ytcp-button.done-button` (text "Done")
- ALSO exists: `ytcp-button.save-button` (for saving new playlist creation)

### Page-level save on edit page
- `ytcp-button#save` exists, text "Save", disabled when no changes
- REQUIRED after playlist dialog closes to persist changes

### Wizard steps: 4 steps, 3 Next clicks (CONFIRMED)
- Details → Video elements → Checks → Visibility
- Current `for _ in range(3)` is correct

### Headless mode: COMPLETELY BLOCKED
- YouTube Studio detects headless Chromium, all selectors fail
- headless=true config WILL NOT WORK
- Must use headful mode for all automation

### Migration status
- tp-yt-*: 36 elements (legacy, declining)
- ytcp-*: 293 elements (dominant)
- Radio buttons still on old tp-yt-paper-radio-button
- Buttons/triggers migrated to ytcp-button, ytcp-dropdown-trigger

### Unverified (upload limit blocker)
- `tp-yt-paper-radio-button[name="PRIVATE"]` on upload wizard step 4
  - Inferred valid: all other radios use same pattern
  - Needs re-verification when limit resets

## [2026-02-23] Task 3: Harden upload() — Scrim Waits + Selector Updates

### Changes made
- Added `DIALOG_SCRIM = "tp-yt-iron-overlay-backdrop"` to constants.py
- All other upload selectors UNCHANGED per manifest (no edits needed)
- Added `_wait_for_scrim_dismissed()` helper — uses `wait_for_selector(state="hidden")`, swallows TimeoutError (scrim doesn't always appear)
- Scrim wait inserted before: not_for_kids.click(), next loop, private_radio.click()
- Replaced `query_selector` → `wait_for_selector` for: NOT_MADE_FOR_KIDS, PRIVATE_RADIO, NEXT_BUTTON, VIDEO_URL_ELEMENT
- Added `except Exception` block with screenshot to `/tmp/yt-recorder-debug-upload-{timestamp}.png`
- Wizard steps confirmed 3 Next clicks — no change

### Patterns
- `wait_for_selector` returns `ElementHandle | None`, null check still appropriate
- Playwright's TimeoutError IS Python's builtin TimeoutError — no special import needed
- `ruff format` collapsed multi-line `wait_for_selector` call to single line — let formatter win
- Task 2 (playlist) ran in parallel and modified assign_playlist — no merge conflict since changes in separate methods

### Tooling
- `uv run` required for mypy/ruff — pyenv shims don't resolve project tools
- mypy --strict: clean (17 files)
- ruff check + format: clean after auto-format

## [2026-02-23] Task 2: Rewrite assign_playlist() + Update Playlist Selectors

### Constants changed (old → new)
- `PLAYLIST_DROPDOWN` → `PLAYLIST_TRIGGER`: `ytcp-video-metadata-playlists ytcp-dropdown-trigger[aria-label="Select playlists"]`
- `PLAYLIST_OPTION_TEMPLATE` → `PLAYLIST_ITEM_TEMPLATE`: `#items tp-yt-paper-checkbox:has-text("{name}")`
- `PLAYLIST_SAVE` → `PLAYLIST_DONE`: `ytcp-button.done-button`
- NEW `PLAYLIST_SEARCH_INPUT`: `ytcp-playlist-dialog #search-input`
- NEW `PLAYLIST_PAGE_SAVE`: `ytcp-button#save`

### Flow changes
- Search-then-select: type playlist name into search input → wait for checkbox → click
- All `query_selector` → `wait_for_selector` with explicit timeouts
- Page-level save step added: click `ytcp-button#save`, wait for `aria-disabled="true"` via `wait_for_function`
- Screenshot on failure: `/tmp/yt-recorder-debug-playlist-{video_id}.png`

### Edge cases handled
- Playlist not found after search: TimeoutError caught, log warning, return False
- Dialog doesn't open (or search hidden with 0 playlists): SelectorChangedError
- Trigger not found: SelectorChangedError (15s timeout, generous for page load)

### Patterns
- `PLAYLIST_TRIGGER` selector needed parenthesized string literal for ruff line length
- Parallel task execution worked cleanly — Task 3 modified upload method, Task 2 modified assign_playlist
- `fill()` safer than `type()` for search input — clears existing content, handles special chars
- mypy --strict, ruff check, ruff format: all clean

## [2026-02-23] Task 4: Update test_youtube.py Mocks

### Changes made
- **TestUpload.test_upload_success**: Updated mocks to use `wait_for_selector` for all dynamic elements (file input, title, not-for-kids, next button, private radio, video URL)
- **TestUpload.test_upload_success**: Added mock for `wait_for_function` (used for done button aria-disabled check)
- **TestUpload.test_upload_success**: Added mock for `DIALOG_SCRIM` selector (returns None, scrim wait swallows TimeoutError)
- **TestUpload.test_upload_success**: Kept `query_selector` mock for title_input and done_button (code still uses query_selector after wait_for_selector)
- **TestAssignPlaylist.test_assign_playlist_success**: Complete rewrite for new flow:
  - Mock `wait_for_selector` for: PLAYLIST_TRIGGER, PLAYLIST_SEARCH_INPUT, PLAYLIST_ITEM_TEMPLATE, PLAYLIST_DONE, PLAYLIST_PAGE_SAVE
  - Mock `search_input.fill()` instead of click
  - Mock `playlist_item.click()` instead of dropdown option click
  - Mock `done_btn.click()` and `page_save_btn.click()` (new page-level save step)
  - Mock `wait_for_function` for page save completion check
  - Assert return value is True
  - Assert all expected calls were made (trigger.click, search_input.fill, playlist_item.click, done_btn.click, page_save_btn.click)

### Test results
- `pytest tests/test_youtube.py -v`: 23/23 PASSED
- `pytest --cov -q`: 179 tests PASSED, 87% coverage, 0 failures
- `ruff check tests/test_youtube.py`: PASSED
- `ruff format tests/test_youtube.py`: Formatted (1 file)
- No old selector references (`tp-yt-paper-button`, `tp-yt-paper-item`, `tp-yt-button-shape`) remain in test file

### Key patterns
- `wait_for_selector` mocks return Mock objects (not None) for elements that should exist
- `wait_for_selector` mocks return None for scrim (state="hidden" wait)
- `query_selector` still used in code for some elements after wait_for_selector — must mock both
- `wait_for_function` mocks return None (success case)
- Test assertions verify both mock calls AND return values

### No regressions
- All 179 tests pass (no test failures in other files)
- Coverage maintained at 87%
- No changes to test_pipeline.py, test_raid.py, test_cli.py (they mock at adapter level, unaffected)

## [2026-02-23] Task 5: Integration QA — FAILED

### QA Result: FAIL — Upload blocked by two bugs

### Bug 1: Wrong TimeoutError exception type (CRITICAL)
- `except TimeoutError:` on 9 lines in youtube.py catches Python's builtin `TimeoutError`
- Playwright's `TimeoutError` (`playwright._impl._errors.TimeoutError`) does NOT subclass Python's `TimeoutError`
- Python `TimeoutError` → OSError → Exception → BaseException
- Playwright `TimeoutError` → playwright.Error → Exception → BaseException
- **Result**: `_wait_for_scrim_dismissed()` never catches timeout, exception propagates, kills upload
- **Task 3 learning was WRONG**: "Playwright's TimeoutError IS Python's builtin TimeoutError" — verified FALSE via `issubclass()` check
- **Fix needed**: `from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError` or use `except Exception:`
- **Scope**: All 9 `except TimeoutError` in youtube.py are affected

### Bug 2: Scrim selector too broad
- `tp-yt-iron-overlay-backdrop` matches 3 elements on upload page
- Playwright picks first: `id="nav-backdrop"` (navigation overlay) — always visible
- `state="hidden"` wait never resolves because nav-backdrop is permanently displayed
- **Fix needed**: More specific selector, e.g., `tp-yt-iron-overlay-backdrop:not(#nav-backdrop)` or target only dialog scrims

### Additional blocker: Daily upload limit
- Screenshot shows "Daily upload limit reached" on YouTube Studio
- This is a YouTube-side rate limit, not a code bug
- Means even with bug fixes, re-test needs to wait for limit reset

### Evidence saved
- `.sisyphus/evidence/task-5-qa-upload.log` — full upload output
- `.sisyphus/evidence/task-5-debug-screenshot.png` — YouTube Studio screenshot showing "Daily upload limit reached"

### Health check: PASSED (9/9)
- Config loads, credentials fresh (0.4 days), Chrome found, yt-dlp found, registry ready

### Status after failure
- `yt-recorder status ~/qa-test-upload` → "qa-test-video.mp4 (not uploaded)"
- File preserved (--keep flag worked even on failure)
- No registry entry created (upload never completed)

### Checklist
- [x] `yt-recorder health` → all checks pass
- [ ] Headful upload succeeds — FAILED (scrim TimeoutError)
- [ ] Playlist assigned — NOT REACHED (upload failed first)
- [ ] No scrim errors — FAILED (scrim wait timeout)
- [ ] Status shows correct state — Shows "not uploaded" (correct for failure)
