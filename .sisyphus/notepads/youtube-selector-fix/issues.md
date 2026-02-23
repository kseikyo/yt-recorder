# Issues — youtube-selector-fix

## [2026-02-23T03:10:42.218Z] Session Start
Session: ses_37785b3f2ffeIGuaPiimWtWMf3
Plan initialized.

## [2026-02-23] BLOCKER: Two bugs prevent upload from completing

### Issue 1: Wrong TimeoutError (P0)
- **File**: `src/yt_recorder/adapters/youtube.py`
- **Lines**: 57, 96, 155, 170, 201, 211, 224, 244, 254
- **Problem**: `except TimeoutError` catches builtin, not Playwright's
- **Impact**: _wait_for_scrim_dismissed always throws, upload() always fails
- **Fix**: Import `from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError`

### Issue 2: Scrim selector matches nav-backdrop (P0)
- **File**: `src/yt_recorder/constants.py` (DIALOG_SCRIM)
- **Problem**: `tp-yt-iron-overlay-backdrop` → 3 matches, first is always-visible nav-backdrop
- **Impact**: Even with correct exception handling, scrim wait would still timeout or silently fail
- **Fix**: `tp-yt-iron-overlay-backdrop:not(#nav-backdrop)` or more specific selector

### Issue 3: Daily upload limit (external)
- YouTube rate-limits uploads per day
- Re-test must wait for limit reset (~24h)
- Not a code bug
