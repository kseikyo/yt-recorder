# Fix YouTube Studio Selectors — Upload + Playlist

> **YouTube migrated from `tp-yt-paper-*` to `ytcp-*` components, breaking playlist assignment (100%) and upload flow (30%).
> Live DOM inspection required before any code changes.**

---

## TL;DR

> **Quick Summary**: Fix all stale YouTube Studio selectors in `constants.py`, rewrite `assign_playlist()` for new dialog flow, add scrim waiting and `wait_for_selector` patterns to `upload()`.
>
> **Deliverables**:
> - Updated `constants.py` with live-verified selectors
> - Rewritten `assign_playlist()` method (new dialog→search→checkbox→done flow)
> - Hardened `upload()` method (scrim waits, `wait_for_selector` replacements)
> - Screenshot-on-failure in error paths
> - Updated test mocks in `test_youtube.py`
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 2 waves after DOM inspection gate
> **Critical Path**: Task 1 (DOM inspect) → Task 2 + Task 3 (parallel) → Task 4 (tests) → Task 5 (integration QA)

---

## Context

### Original Request

User ran `yt-recorder upload ~/Desktop/recordings` and observed:
- **9/9 playlist assignments failed** (100% failure — "Playlist dropdown not found")
- **4/13 uploads failed** (intermittent — title timeout, next button hidden, dialog scrim blocking clicks)
- **9/13 uploads succeeded** (selectors partially working, YouTube mid-migration)

### Error Taxonomy (from real upload run)

**Category 1 — Playlist (100% failure)**:
- `tp-yt-paper-button[aria-label*="Playlist"]` → dead selector
- `tp-yt-paper-item:has-text('{name}')` → dead selector
- `tp-yt-button-shape[aria-label='Save']` → dead selector
- `query_selector` used (instant, no wait) — element never exists

**Category 2 — Upload dialog scrim (intermittent)**:
- `<div class="dialog-scrim style-scope ytcp-uploads-dialog">` intercepts pointer events
- Blocks: `not_for_kids.click()` (L109), `next_btn.click()` (L117)
- Cascade: blocked clicks → form incomplete → next button hidden

**Category 3 — Upload selectors (partially stale)**:
- `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` (L10) — `tp-yt-*`
- `tp-yt-paper-radio-button[name="PRIVATE"]` (L14) — `tp-yt-*`
- Works 69% of time (YouTube mid-migration, A/B testing)

### Research Findings

- OSS projects confirm `tp-yt-paper-*` → `ytcp-*` migration in YouTube Studio
- New playlist flow uses: `ytcp-video-metadata-playlists` trigger, `#search-input`, `#items` container with checkboxes, `ytcp-button.save-button`
- `#title-textarea #textbox`, `#next-button`, `#done-button` (ID-based) are likely stable but need verification
- `tp-yt-paper-button` still exists on YouTube's public pages, but Studio editor migrated

### Metis Review

**Key gaps identified (addressed in plan)**:
1. Playlist may not pre-exist → keep current behavior (return False), don't add creation flow
2. Wizard step count (`for _ in range(3)`) needs verification — could have changed
3. Headless vs headful mode may render different selectors → verify in both
4. After playlist dialog "done", page-level save may be required
5. Playlist names with special chars could break CSS selectors → use search input
6. Multiple scrim layers could stack → wait for ALL `.dialog-scrim` to be hidden

---

## Work Objectives

### Core Objective
Fix all YouTube Studio selectors and interaction patterns so upload + playlist assignment work reliably.

### Concrete Deliverables
- `src/yt_recorder/constants.py` — updated selectors (verified against live DOM)
- `src/yt_recorder/adapters/youtube.py` — rewritten `assign_playlist()`, hardened `upload()`
- `tests/test_youtube.py` — updated mocks for new selectors and wait patterns

### Definition of Done
- [ ] `yt-recorder upload ~/test-dir --keep --limit 1` succeeds with playlist assigned
- [ ] `yt-recorder upload ~/test-dir --keep --limit 1 --headless` succeeds (headless mode)
- [ ] `pytest tests/test_youtube.py -v` → all pass
- [ ] `mypy --strict src` → 0 issues
- [ ] `ruff check src tests && ruff format --check src tests` → 0 errors
- [ ] `pytest --cov -q` → 179+ tests, 0 failures

### Must Have
- All selectors verified against live YouTube Studio DOM
- `assign_playlist()` rewritten for dialog→search→checkbox→done flow
- `wait_for_selector` replacing all `query_selector` calls for dynamic elements
- Scrim wait before form interactions in `upload()`
- Screenshot-on-failure in except blocks (to `/tmp/yt-recorder-debug-*.png`)
- Wizard step count verified (currently hardcoded as 3)

### Must NOT Have (Guardrails)
- NO public API changes to `YouTubeBrowserAdapter` (method signatures stay identical)
- NO new exception types (use existing `SelectorChangedError`)
- NO retry/resilience framework (only `wait_for_selector` with timeouts)
- NO selector fallback chains ("try new, fall back to old")
- NO changes outside `constants.py`, `youtube.py`, `test_youtube.py`
- NO config options for screenshots or debug paths
- NO playlist creation flow (if playlist doesn't exist, return False as now)
- NO architecture changes (no Page Object pattern, no abstraction layers)
- NO changes to pipeline.py, raid.py, cli.py, domain/, or other test files

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest + pytest-cov)
- **Automated tests**: YES (tests-after — update existing mocks)
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

| Deliverable Type | Verification Tool | Method |
|------------------|-------------------|--------|
| DOM inspection artifact | Bash (file check) | Verify markdown table exists with all selectors |
| Selector updates | pytest | Unit tests with updated mocks |
| Upload flow | Playwright (tmux) | Headful upload with observation |
| Playlist flow | Playwright (tmux) | Headful playlist assignment with observation |
| Regression | Bash | `pytest && mypy --strict && ruff check` |

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (BLOCKING — must complete before anything else):
└── Task 1: Live DOM inspection → selector manifest [deep]

Wave 2 (After Wave 1 — parallel):
├── Task 2: Update constants.py + rewrite assign_playlist() [deep]
└── Task 3: Harden upload() — scrim waits + selector updates [unspecified-high]

Wave 3 (After Wave 2 — sequential):
└── Task 4: Update test_youtube.py mocks [quick]

Wave 4 (After Wave 3 — verification):
└── Task 5: Integration QA — real upload + playlist in headful mode [unspecified-high]

Critical Path: Task 1 → Task 2 → Task 4 → Task 5
Parallel Speedup: Task 2 + Task 3 run simultaneously
Max Concurrent: 2 (Wave 2)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|------------|--------|------|
| 1 | — | 2, 3 | 1 |
| 2 | 1 | 4 | 2 |
| 3 | 1 | 4 | 2 |
| 4 | 2, 3 | 5 | 3 |
| 5 | 4 | — | 4 |

### Agent Dispatch Summary

| Wave | # Parallel | Tasks → Agent Category |
|------|------------|----------------------|
| 1 | **1** | T1 → `deep` (with `dev-browser` skill) |
| 2 | **2** | T2 → `deep`, T3 → `unspecified-high` |
| 3 | **1** | T4 → `quick` |
| 4 | **1** | T5 → `unspecified-high` (with `dev-browser` skill) |

---

## TODOs

- [ ] 1. Live DOM Inspection — Capture Current YouTube Studio Selectors

  **What to do**:
  - Pre-flight: Run `yt-recorder health` to verify session is valid. If expired, STOP and report.
  - Start dev-browser in extension mode (connects to user's authenticated Chrome)
  - Navigate to `https://www.youtube.com/upload` in the dev-browser page
  - Upload a small test file (or observe the upload dialog structure without completing)
  - Capture the DOM tree around these elements:
    - File picker container
    - Title textarea input
    - "Not made for kids" radio button
    - Next button
    - Private/Unlisted/Public radio buttons
    - Done button
    - Dialog scrim overlay element
    - Video URL element
  - Count the number of wizard steps (currently assumed to be 3 "Next" clicks)
  - Navigate to `https://studio.youtube.com/video/{video_id}/edit` (use a video from the user's recent uploads)
  - Capture the DOM tree around playlist section:
    - Playlist dropdown/trigger element
    - Playlist dialog container
    - Search input inside dialog
    - Playlist items/checkboxes
    - Done/Save button inside dialog
  - Check if page-level save is required after playlist dialog closes
  - Test both headful and headless rendering (compare selector availability)
  - Produce a **Selector Manifest** — markdown table saved to `.sisyphus/evidence/task-1-selector-manifest.md`:
    ```
    | Element | Old Selector | New Selector | Verified | Notes |
    |---------|-------------|-------------|----------|-------|
    | Title input | #title-textarea #textbox | ??? | ✓/✗ | |
    ```

  **Must NOT do**:
  - Do NOT complete any actual uploads (just observe DOM structure)
  - Do NOT modify any code files
  - Do NOT guess selectors — every entry must be verified against live DOM
  - Do NOT use OSS research selectors without live verification

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires careful DOM exploration, multiple pages, iterative discovery
  - **Skills**: [`dev-browser`]
    - `dev-browser`: Required for browser automation to inspect YouTube Studio DOM

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (solo — blocking gate)
  - **Blocks**: Tasks 2, 3
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `src/yt_recorder/constants.py:1-32` — Current selectors (the "old" column in manifest)
  - `src/yt_recorder/adapters/youtube.py:73-171` — Upload flow showing which selectors are used where
  - `src/yt_recorder/adapters/youtube.py:173-213` — Playlist flow showing which selectors are used where

  **External References**:
  - `https://github.com/linouk23/youtube_uploader_selenium/blob/master/youtube_uploader_selenium/Constant.py` — OSS selector reference (hypothesis, NOT source of truth)
  - `https://github.com/fawazahmed0/youtube-uploader/blob/main/src/upload.ts` — Another OSS reference for playlist XPath patterns

  **WHY Each Reference Matters**:
  - `constants.py` — provides the "old selector" column and the element names to search for
  - `youtube.py` upload flow — shows which selectors are critical (used with `wait_for_selector` vs `query_selector`)
  - OSS references — starting hypotheses for where to look in the DOM, NOT to be blindly copied

  **Acceptance Criteria**:
  - [ ] `.sisyphus/evidence/task-1-selector-manifest.md` exists
  - [ ] Manifest has entries for ALL 12 elements: file picker, title input, not-for-kids radio, next button, private radio, done button, dialog scrim, video URL, playlist trigger, playlist search, playlist item, playlist save
  - [ ] Every "New Selector" column is populated (no "???" remaining)
  - [ ] Every entry has "Verified: ✓" (tested against live DOM)
  - [ ] Wizard step count documented (how many "Next" clicks needed)
  - [ ] Page-level save requirement after playlist documented (YES/NO)
  - [ ] Headless vs headful selector differences documented (if any)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Selector manifest completeness
    Tool: Bash
    Preconditions: Task 1 completed, manifest file exists
    Steps:
      1. Read .sisyphus/evidence/task-1-selector-manifest.md
      2. Count rows in the selector table
      3. Grep for "???" or empty cells
      4. Grep for "✗" in Verified column
    Expected Result: 12+ rows, 0 "???" entries, 0 "✗" entries
    Failure Indicators: Missing elements, unverified selectors
    Evidence: .sisyphus/evidence/task-1-manifest-validation.txt

  Scenario: Upload page screenshot captured
    Tool: Bash
    Preconditions: Dev-browser session completed
    Steps:
      1. Check for screenshot file at .sisyphus/evidence/task-1-upload-page.png
      2. Check for screenshot file at .sisyphus/evidence/task-1-edit-page.png
      3. Check for screenshot file at .sisyphus/evidence/task-1-playlist-dialog.png
    Expected Result: All 3 screenshots exist with >0 bytes
    Failure Indicators: Missing screenshots, 0-byte files
    Evidence: .sisyphus/evidence/task-1-upload-page.png
  ```

  **Evidence to Capture:**
  - [ ] `.sisyphus/evidence/task-1-selector-manifest.md` — The selector manifest table
  - [ ] `.sisyphus/evidence/task-1-upload-page.png` — Screenshot of upload dialog
  - [ ] `.sisyphus/evidence/task-1-edit-page.png` — Screenshot of video edit page
  - [ ] `.sisyphus/evidence/task-1-playlist-dialog.png` — Screenshot of playlist dialog open

  **Commit**: NO (research task, no code changes)

---

- [ ] 2. Rewrite assign_playlist() + Update Playlist Selectors

  **What to do**:
  - Read selector manifest from `.sisyphus/evidence/task-1-selector-manifest.md`
  - Update `constants.py` lines 29-32 with verified playlist selectors:
    - `PLAYLIST_TRIGGER` — the element that opens the playlist dialog (replaces `PLAYLIST_DROPDOWN`)
    - `PLAYLIST_SEARCH_INPUT` — search field inside the dialog (NEW)
    - `PLAYLIST_ITEM_TEMPLATE` — checkbox/item for a specific playlist (replaces `PLAYLIST_OPTION_TEMPLATE`)
    - `PLAYLIST_DONE` — done/save button inside dialog (replaces `PLAYLIST_SAVE`)
  - Rewrite `youtube.py` `assign_playlist()` method (lines 173-213) with new flow:
    1. Navigate to edit URL with `wait_until="domcontentloaded"`
    2. Session/bot checks (keep existing)
    3. `wait_for_selector(PLAYLIST_TRIGGER, timeout=15000)` — wait for page to fully load
    4. Click playlist trigger to open dialog
    5. `wait_for_selector(PLAYLIST_SEARCH_INPUT, timeout=5000)` — wait for dialog to open
    6. Type playlist name into search input (handles special chars safely)
    7. `wait_for_selector(PLAYLIST_ITEM_TEMPLATE.format(...), timeout=5000)` — wait for results
    8. Click the matching playlist checkbox
    9. `wait_for_selector(PLAYLIST_DONE, timeout=5000)` — find done button
    10. Click done
    11. If page-level save required (from manifest): click save button, wait for confirmation
    12. Return True
  - Handle edge cases:
    - Search returns no results → log warning, return False (don't timeout)
    - Playlist dialog doesn't open → SelectorChangedError (not warning)
  - Add screenshot-on-failure in the except block:
    ```python
    except Exception:
        page.screenshot(path=f"/tmp/yt-recorder-debug-playlist-{video_id}.png")
        raise
    ```
  - Preserve method signature: `def assign_playlist(self, video_id: str, playlist_name: str) -> bool`

  **Must NOT do**:
  - Do NOT add playlist creation flow
  - Do NOT add retry loops
  - Do NOT change method signature
  - Do NOT add selector fallback chains
  - Do NOT touch upload() method (that's Task 3)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Method rewrite with new interaction model, edge case handling, must match manifest exactly
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3)
  - **Parallel Group**: Wave 2 (with Task 3)
  - **Blocks**: Task 4
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `.sisyphus/evidence/task-1-selector-manifest.md` — Source of truth for all selectors
  - `src/yt_recorder/adapters/youtube.py:73-171` — Upload method as pattern for `wait_for_selector` usage (lines 86-88 show the pattern)
  - `src/yt_recorder/adapters/youtube.py:173-213` — Current assign_playlist to rewrite
  - `src/yt_recorder/domain/exceptions.py` — SelectorChangedError definition

  **API/Type References**:
  - `src/yt_recorder/domain/protocols.py:46` — `assign_playlist` protocol signature (must match)
  - `src/yt_recorder/constants.py:29-32` — Current playlist selectors to replace

  **External References**:
  - Playwright `wait_for_selector` docs: timeout, state options

  **WHY Each Reference Matters**:
  - Selector manifest is the ONLY source of truth for new selectors — do not deviate
  - Upload method shows the existing `wait_for_selector` pattern to follow
  - Protocol signature must not change — pipeline and RAID depend on it

  **Acceptance Criteria**:
  - [ ] `constants.py` has updated playlist selectors matching manifest exactly
  - [ ] `assign_playlist()` uses `wait_for_selector` for every dynamic element
  - [ ] `assign_playlist()` types playlist name into search input (not CSS selector matching)
  - [ ] Screenshot captured on failure to `/tmp/yt-recorder-debug-playlist-{video_id}.png`
  - [ ] Method signature unchanged: `def assign_playlist(self, video_id: str, playlist_name: str) -> bool`
  - [ ] `mypy --strict src` → passes
  - [ ] `ruff check src && ruff format --check src` → passes
  - [ ] No new exception types added

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: assign_playlist method signature preserved
    Tool: Bash (ast-grep)
    Preconditions: Code changes complete
    Steps:
      1. ast-grep search for 'def assign_playlist(self, video_id: str, playlist_name: str) -> bool' in youtube.py
      2. Verify exactly 1 match
    Expected Result: 1 match found with identical signature
    Failure Indicators: 0 matches (signature changed) or different return type
    Evidence: .sisyphus/evidence/task-2-signature-check.txt

  Scenario: All query_selector calls replaced in assign_playlist
    Tool: Bash (grep)
    Preconditions: Code changes complete
    Steps:
      1. grep -n 'query_selector' src/yt_recorder/adapters/youtube.py
      2. Verify no matches between lines 173-213 (assign_playlist method)
    Expected Result: Zero query_selector calls within assign_playlist body
    Failure Indicators: Any query_selector remaining in the method
    Evidence: .sisyphus/evidence/task-2-no-query-selector.txt

  Scenario: Screenshot-on-failure present
    Tool: Bash (grep)
    Preconditions: Code changes complete
    Steps:
      1. grep -n 'screenshot' src/yt_recorder/adapters/youtube.py
      2. Verify at least 1 match in assign_playlist method
    Expected Result: page.screenshot call in except block
    Failure Indicators: No screenshot call found
    Evidence: .sisyphus/evidence/task-2-screenshot-check.txt

  Scenario: Mypy + ruff pass
    Tool: Bash
    Preconditions: Code changes complete
    Steps:
      1. Run: mypy --strict src
      2. Run: ruff check src && ruff format --check src
    Expected Result: 0 errors on both
    Failure Indicators: Any type error or lint error
    Evidence: .sisyphus/evidence/task-2-lint-check.txt
  ```

  **Commit**: YES
  - Message: `fix: rewrite assign_playlist for ytcp dialog flow + wait_for_selector`
  - Files: `src/yt_recorder/constants.py`, `src/yt_recorder/adapters/youtube.py`
  - Pre-commit: `mypy --strict src && ruff check src`

---

- [ ] 3. Harden upload() — Scrim Waits + Selector Updates

  **What to do**:
  - Read selector manifest from `.sisyphus/evidence/task-1-selector-manifest.md`
  - Update `constants.py` upload selectors (lines 9-15) with verified values:
    - `NOT_MADE_FOR_KIDS` — replace `tp-yt-paper-radio-button` if manifest shows new component
    - `PRIVATE_RADIO` — replace `tp-yt-paper-radio-button` if manifest shows new component
    - `TITLE_INPUT`, `NEXT_BUTTON`, `DONE_BUTTON` — update only if manifest shows they changed
    - Add `DIALOG_SCRIM` constant for the scrim overlay selector
  - Add scrim wait helper in `youtube.py`:
    ```python
    def _wait_for_scrim_dismissed(self, page: Page, timeout: int = 10000) -> None:
        """Wait for upload dialog scrim to disappear before interacting."""
        try:
            page.wait_for_selector(
                constants.DIALOG_SCRIM, state="hidden", timeout=timeout
            )
        except TimeoutError:
            pass  # Scrim may not appear for every action
    ```
  - Insert scrim wait calls before these interactions in `upload()`:
    - Before `not_for_kids.click()` (L109) — this is where scrim blocked clicks
    - Before the 3×Next loop (L113) — scrim could reappear between steps
    - Before `private_radio.click()` (L123) — safety
  - Replace `query_selector` with `wait_for_selector` for these elements in `upload()`:
    - `NOT_MADE_FOR_KIDS` (L106) — currently `query_selector`, should be `wait_for_selector`
    - `PRIVATE_RADIO` (L120) — currently `query_selector`, should be `wait_for_selector`
    - `NEXT_BUTTON` (L114) — currently `query_selector`, should be `wait_for_selector`
    - `VIDEO_URL_ELEMENT` (L127) — currently `query_selector`, should be `wait_for_selector`
  - Update wizard step count if manifest shows it changed from 3
  - Add screenshot-on-failure in upload's except path:
    ```python
    except Exception:
        page.screenshot(path=f"/tmp/yt-recorder-debug-upload-{int(time.time())}.png")
        raise
    ```

  **Must NOT do**:
  - Do NOT touch `assign_playlist()` (that's Task 2)
  - Do NOT add retry loops or exponential backoff
  - Do NOT change method signature of `upload()`
  - Do NOT change the `wait_for_function` logic for done button (L138-145) — it works
  - Do NOT change file picker logic (L85-94) — it works

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Surgical changes to existing method, following clear patterns from manifest
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2)
  - **Parallel Group**: Wave 2 (with Task 2)
  - **Blocks**: Task 4
  - **Blocked By**: Task 1

  **References**:

  **Pattern References**:
  - `.sisyphus/evidence/task-1-selector-manifest.md` — Source of truth for selectors
  - `src/yt_recorder/adapters/youtube.py:85-93` — `wait_for_selector` pattern to replicate (file picker has the right approach)
  - `src/yt_recorder/adapters/youtube.py:158-162` — `wait_for_selector(state="hidden")` pattern for scrim

  **API/Type References**:
  - `src/yt_recorder/domain/protocols.py:30-43` — Upload protocol signature (must match)
  - `src/yt_recorder/constants.py:9-15` — Upload selectors to update

  **WHY Each Reference Matters**:
  - Line 85-93 shows the correct `wait_for_selector` + `state="attached"` pattern — replicate for all dynamic elements
  - Line 158-162 shows `state="hidden"` wait — exact pattern needed for scrim dismissal
  - Manifest is the ONLY source for selector values

  **Acceptance Criteria**:
  - [ ] `constants.py` has `DIALOG_SCRIM` selector
  - [ ] `constants.py` upload selectors match manifest
  - [ ] `_wait_for_scrim_dismissed` helper added to `YouTubeBrowserAdapter`
  - [ ] Scrim wait called before `not_for_kids.click()`, next loop, `private_radio.click()`
  - [ ] `query_selector` replaced with `wait_for_selector` for: NOT_MADE_FOR_KIDS, PRIVATE_RADIO, NEXT_BUTTON, VIDEO_URL_ELEMENT
  - [ ] Wizard step count matches manifest (update `range(3)` if needed)
  - [ ] Screenshot captured on failure
  - [ ] Method signature unchanged
  - [ ] `mypy --strict src` → passes
  - [ ] `ruff check src && ruff format --check src` → passes

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Scrim wait present before critical clicks
    Tool: Bash (grep)
    Preconditions: Code changes complete
    Steps:
      1. grep -n '_wait_for_scrim_dismissed' src/yt_recorder/adapters/youtube.py
      2. Verify at least 3 calls within upload() method
    Expected Result: 3+ calls to scrim wait in upload method
    Failure Indicators: Fewer than 3 calls
    Evidence: .sisyphus/evidence/task-3-scrim-waits.txt

  Scenario: No query_selector for dynamic elements in upload()
    Tool: Bash (grep)
    Preconditions: Code changes complete
    Steps:
      1. grep -n 'query_selector.*NOT_MADE_FOR_KIDS\|query_selector.*PRIVATE_RADIO\|query_selector.*NEXT_BUTTON\|query_selector.*VIDEO_URL' src/yt_recorder/adapters/youtube.py
    Expected Result: Zero matches
    Failure Indicators: Any query_selector remaining for these selectors
    Evidence: .sisyphus/evidence/task-3-no-query-selector.txt

  Scenario: Mypy + ruff pass
    Tool: Bash
    Preconditions: Code changes complete
    Steps:
      1. Run: mypy --strict src
      2. Run: ruff check src && ruff format --check src
    Expected Result: 0 errors on both
    Failure Indicators: Any type error or lint error
    Evidence: .sisyphus/evidence/task-3-lint-check.txt
  ```

  **Commit**: YES (groups with Task 2 if ready simultaneously)
  - Message: `fix: upload scrim waits + wait_for_selector + updated selectors`
  - Files: `src/yt_recorder/constants.py`, `src/yt_recorder/adapters/youtube.py`
  - Pre-commit: `mypy --strict src && ruff check src`

---

- [ ] 4. Update test_youtube.py Mocks

  **What to do**:
  - Read the updated `constants.py` to get new selector values
  - Update all test mocks in `test_youtube.py` that reference old selectors:
    - `tp-yt-paper-button` → new playlist trigger selector
    - `tp-yt-paper-item` → new playlist item selector
    - `tp-yt-button-shape` → new playlist done selector
    - `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` → new selector (if changed)
    - `tp-yt-paper-radio-button[name="PRIVATE"]` → new selector (if changed)
  - Update `TestAssignPlaylist` test class to match new flow:
    - Mock the search input interaction (type playlist name)
    - Mock the checkbox click (instead of dropdown item click)
    - Mock the done button (instead of save button)
    - Add mock for `wait_for_selector` calls (instead of `query_selector`)
  - Update `TestUpload` test class:
    - Add mock for `_wait_for_scrim_dismissed`
    - Update `wait_for_selector` mocks if selectors changed
  - Verify: `pytest tests/test_youtube.py -v` → all pass
  - Verify: `pytest --cov -q` → no regression (179+ tests)

  **Must NOT do**:
  - Do NOT change tests in test_pipeline.py, test_raid.py, test_cli.py (they mock at adapter level)
  - Do NOT add new test files
  - Do NOT change test structure beyond mock updates

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Mechanical mock updates following new selectors, not creative work
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential — needs Tasks 2+3 complete)
  - **Blocks**: Task 5
  - **Blocked By**: Tasks 2, 3

  **References**:

  **Pattern References**:
  - `tests/test_youtube.py` — Current test file (read fully to find all selector references)
  - `src/yt_recorder/constants.py` — Updated selectors (after Tasks 2+3)
  - `src/yt_recorder/adapters/youtube.py` — Updated methods to understand what to mock

  **WHY Each Reference Matters**:
  - test_youtube.py has hardcoded selector strings in mocks — must match new constants exactly
  - constants.py provides the new values to use in mocks
  - youtube.py shows the new wait_for_selector calls that need mocking

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_youtube.py -v` → all pass
  - [ ] `pytest --cov -q` → 179+ tests, 0 failures
  - [ ] `mypy --strict src tests` → passes (if tests are typed)
  - [ ] No references to `tp-yt-paper-button`, `tp-yt-paper-item`, or `tp-yt-button-shape` in test file
  - [ ] `TestAssignPlaylist` tests mock the new flow (search→checkbox→done)
  - [ ] `TestUpload` tests mock `_wait_for_scrim_dismissed`

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: All tests pass
    Tool: Bash
    Preconditions: Test updates complete
    Steps:
      1. Run: pytest tests/test_youtube.py -v
      2. Run: pytest --cov -q
    Expected Result: All tests pass, 179+ total, 0 failures
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-4-test-results.txt

  Scenario: No old selector references in tests
    Tool: Bash (grep)
    Preconditions: Test updates complete
    Steps:
      1. grep -n 'tp-yt-paper-button\|tp-yt-paper-item\|tp-yt-button-shape' tests/test_youtube.py
    Expected Result: Zero matches
    Failure Indicators: Any old selector reference remaining
    Evidence: .sisyphus/evidence/task-4-no-old-selectors.txt

  Scenario: Full regression suite
    Tool: Bash
    Preconditions: All code + test changes complete
    Steps:
      1. Run: ruff check src tests && ruff format --check src tests
      2. Run: mypy --strict src
      3. Run: pytest --cov -q
    Expected Result: 0 lint errors, 0 type errors, 179+ tests pass
    Failure Indicators: Any failure in any check
    Evidence: .sisyphus/evidence/task-4-full-regression.txt
  ```

  **Commit**: YES
  - Message: `test: update youtube mocks for ytcp selectors + new playlist flow`
  - Files: `tests/test_youtube.py`
  - Pre-commit: `pytest tests/test_youtube.py -v && mypy --strict src`

---

- [ ] 5. Integration QA — Real Upload + Playlist Assignment

  **What to do**:
  - This is an agent-executed QA task, not a code task
  - Run `yt-recorder health` to verify credentials
  - Create a test directory with a small video file (~10MB)
  - Run headful upload: `yt-recorder upload ~/test-dir --keep --limit 1 -v`
  - Observe and verify:
    - Upload dialog opens without scrim blocking
    - Title input filled correctly
    - Not-for-kids radio clicked without scrim interference
    - Next button clicks succeed (all steps)
    - Private radio selected
    - Done button clicked after upload completes
    - Playlist assigned successfully (no "Playlist dropdown not found" warning)
  - Run headless upload: `yt-recorder upload ~/test-dir --keep --limit 1 -v`
  - Verify same success in headless mode
  - Check `yt-recorder status ~/test-dir` shows correct state
  - If any failure: capture screenshot, log the error, report back with details

  **Must NOT do**:
  - Do NOT modify code — this is verification only
  - Do NOT mark as passed if ANY playlist assignment fails

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Real browser interaction requiring observation and debugging
  - **Skills**: [`dev-browser`]
    - `dev-browser`: For running and observing the browser automation

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (final verification)
  - **Blocks**: None
  - **Blocked By**: Task 4

  **References**:

  **Pattern References**:
  - `.sisyphus/evidence/task-1-selector-manifest.md` — Reference for what selectors should be used
  - `src/yt_recorder/cli.py` — CLI entry points for upload/status commands

  **WHY Each Reference Matters**:
  - Manifest tells us what selectors we expect to work — if QA fails, compare actual DOM against manifest

  **Acceptance Criteria**:
  - [ ] `yt-recorder health` → all checks pass
  - [ ] Headful upload succeeds (1 video uploaded)
  - [ ] Playlist assigned successfully (no "Playlist dropdown not found")
  - [ ] No "dialog-scrim intercepts pointer events" errors
  - [ ] Headless upload succeeds (1 video uploaded)
  - [ ] `yt-recorder status ~/test-dir` → shows uploaded video with correct playlist

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Headful upload + playlist assignment
    Tool: Bash (interactive_bash for observation)
    Preconditions: Credentials valid, test video available
    Steps:
      1. Run: yt-recorder health
      2. Run: yt-recorder upload ~/test-dir --keep --limit 1 -v 2>&1 | tee /tmp/yt-upload-headful.log
      3. grep 'Playlist dropdown not found' /tmp/yt-upload-headful.log
      4. grep 'Playlist assignment failed' /tmp/yt-upload-headful.log
      5. grep 'dialog-scrim' /tmp/yt-upload-headful.log
    Expected Result: Upload succeeds, 0 playlist warnings, 0 scrim errors
    Failure Indicators: Any WARNING or ERROR in the log
    Evidence: .sisyphus/evidence/task-5-headful-upload.log

  Scenario: Headless upload + playlist assignment
    Tool: Bash
    Preconditions: Headful test passed
    Steps:
      1. Run: yt-recorder upload ~/test-dir --keep --limit 1 -v 2>&1 | tee /tmp/yt-upload-headless.log
      2. Same grep checks as headful scenario
    Expected Result: Upload succeeds, 0 playlist warnings, 0 scrim errors
    Failure Indicators: Any WARNING or ERROR in the log
    Evidence: .sisyphus/evidence/task-5-headless-upload.log

  Scenario: Status verification
    Tool: Bash
    Preconditions: At least 1 successful upload
    Steps:
      1. Run: yt-recorder status ~/test-dir
      2. Verify output shows uploaded video with playlist name
    Expected Result: Video listed with correct playlist
    Failure Indicators: Missing video or missing playlist name
    Evidence: .sisyphus/evidence/task-5-status-output.txt
  ```

  **Commit**: NO (QA task, no code changes)

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | — (no commit, research only) | — | Manifest exists |
| 2 | `fix: rewrite assign_playlist for ytcp dialog flow + wait_for_selector` | constants.py, youtube.py | mypy + ruff |
| 3 | `fix: upload scrim waits + wait_for_selector + updated selectors` | constants.py, youtube.py | mypy + ruff |
| 4 | `test: update youtube mocks for ytcp selectors + new playlist flow` | test_youtube.py | pytest + mypy |
| 5 | — (no commit, QA only) | — | Real upload succeeds |

Note: Tasks 2 and 3 both modify `constants.py` and `youtube.py`. If they complete simultaneously, the second commit will need to resolve any merge conflicts in these files. Alternatively, they can be committed together:
- Combined: `fix: youtube selectors — upload scrim waits + playlist dialog rewrite`

---

## Success Criteria

- [ ] `yt-recorder upload ~/test-dir --keep --limit 1` → upload succeeds
- [ ] Playlist assigned (no "Playlist dropdown not found" warning)
- [ ] No "dialog-scrim intercepts pointer events" errors
- [ ] `pytest --cov -q` → 179+ tests, 0 failures
- [ ] `mypy --strict src` → 0 issues
- [ ] `ruff check src tests && ruff format --check src tests` → 0 errors
- [ ] Selector manifest exists at `.sisyphus/evidence/task-1-selector-manifest.md`
- [ ] No `tp-yt-paper-*` selectors remaining in constants.py or test files
- [ ] No `query_selector` calls in `assign_playlist()` method
- [ ] Scrim wait present before all critical clicks in `upload()`

## Dependency Graph

```
Task 1 (DOM inspection)
  ├── Task 2 (playlist rewrite)  ──┐
  └── Task 3 (upload hardening)  ──├── Task 4 (test updates) → Task 5 (integration QA)
```

Tasks 2 and 3 are parallel. Everything else sequential.
