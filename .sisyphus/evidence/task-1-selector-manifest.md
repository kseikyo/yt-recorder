# YouTube Studio Selector Manifest

**Inspection Date**: 2026-02-23
**Test Mode**: Headful + Headless comparison
**Video Used**: O0O330BMtgM (edit page inspection)
**Account**: primary (session fresh, 0.1 days old)

## Upload Flow Selectors

| Element | Old Selector | New Selector | Verified | Notes |
|---------|-------------|-------------|----------|-------|
| File Picker | `ytcp-uploads-file-picker` | `ytcp-uploads-file-picker` | ✓ | Unchanged. id=`ytcp-uploads-dialog-file-picker`. Tag: YTCP-UPLOADS-FILE-PICKER |
| File Input | `input[type="file"]` | `input[type="file"]` | ✓ | Unchanged. Parent: DIV#content. Used with `set_input_files()` successfully |
| Title Input | `#title-textarea #textbox` | `#title-textarea #textbox` | ✓ | Unchanged. Tag: DIV, contenteditable="true". aria-label: "Add a title that describes your video (type @ to mention a channel)" |
| Not For Kids Radio | `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` | `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` | ✓ | Unchanged. Tag: TP-YT-PAPER-RADIO-BUTTON. Still uses old `tp-yt-` prefix. Parent: TP-YT-PAPER-RADIO-GROUP |
| Next Button | `#next-button` | `#next-button` | ✓ | Unchanged. Tag: YTCP-BUTTON. Text: "Next". Has aria-disabled attribute |
| Private Radio | `tp-yt-paper-radio-button[name="PRIVATE"]` | `tp-yt-paper-radio-button[name="PRIVATE"]` | ⚠ | NOT directly verified — daily upload limit blocked reaching visibility step. Inferred: all other radios (not-for-kids, age-restriction) still use `tp-yt-paper-radio-button`, so PRIVATE likely unchanged. **Needs re-verification when upload limit resets** |
| Done Button | `#done-button` | `#done-button` | ✓ | Tag: YTCP-BUTTON. **IMPORTANT: Button text is now "Save" (not "Done")**. Has aria-disabled attribute. Disabled until upload completes |
| Dialog Scrim | _(none in old code)_ | `tp-yt-iron-overlay-backdrop` | ✓ | Tag: TP-YT-IRON-OVERLAY-BACKDROP. display: block, zIndex: 1. Multiple instances exist (3 on upload page). This is the element that blocks clicks — must handle in automation |
| Video URL Element | `span.video-url-fadeable a` | `span.video-url-fadeable a` | ✓ | Unchanged. Tag: A. Parent: SPAN.video-url-fadeable. href is empty during upload processing, populates after YouTube assigns video ID |

## Playlist Flow Selectors

| Element | Old Selector | New Selector | Verified | Notes |
|---------|-------------|-------------|----------|-------|
| Playlist Trigger | `tp-yt-paper-button[aria-label*="Playlist"]` | `ytcp-video-metadata-playlists ytcp-dropdown-trigger[aria-label="Select playlists"]` | ✓ | **BREAKING CHANGE**. Old `tp-yt-paper-button` gone. New: ytcp-dropdown-trigger inside ytcp-video-metadata-playlists. Text: "Select". The component `ytcp-video-metadata-playlists` has aria-label="Add to playlist" |
| Playlist Dialog | _(none)_ | `tp-yt-paper-dialog.ytcp-playlist-dialog` | ✓ | aria-label="Choose playlists". Opens as modal overlay. Contains search, items, and action buttons |
| Playlist Search Input | _(none)_ | `ytcp-playlist-dialog #search-input` | ✓ | YTCP-SEARCH-BAR#search-input, placeholder="Search for a playlist". Inner input: `input#search-input[aria-label="Search for a playlist"]`. Hidden when 0 playlists exist (div#search has `hidden=""` attr) |
| Playlist Item | `tp-yt-paper-item:has-text('{name}')` | `tp-yt-paper-checkbox` (inside `#items` container) | ⚠ | **BREAKING CHANGE**. Old used `tp-yt-paper-item`. New uses `tp-yt-paper-checkbox` inside `div#items`. Could not verify checkbox interaction — channel has 0 playlists. Pattern: check/uncheck checkboxes, not click items |
| Playlist Done/Save | `tp-yt-button-shape[aria-label='Save']` | `ytcp-button.done-button` | ✓ | **BREAKING CHANGE**. Class: `done-button action-button style-scope ytcp-playlist-dialog`. Text: "Done". There is ALSO a `ytcp-button.save-button` (text "Save") in the dialog — that one is for saving a newly created playlist. Use `.done-button` to close after selecting playlists |

## Critical Findings

### Wizard Steps

**COUNT: 4 steps, 3 Next button clicks needed**

| Step | Name | Key Elements |
|------|------|-------------|
| 1 | Details | Title input, description, thumbnail, not-for-kids radio |
| 2 | Video elements | Subtitles, end screen, cards (all optional) |
| 3 | Checks | Copyright/content checks (auto) |
| 4 | Visibility | Private/Unlisted/Public radios, schedule |

Current code uses `for _ in range(3)` which is **CORRECT** — 3 Next clicks moves from step 1 to step 4.

### Page-Level Save After Playlist

**YES** — `ytcp-button#save` exists on edit page. Tag: YTCP-BUTTON, text: "Save", aria-disabled="true" when no changes pending. After making playlist changes and closing the playlist dialog, this page-level save button must be clicked to persist changes.

### Headless vs Headful Differences

**CRITICAL: Headless mode is completely blocked by YouTube Studio.**

All selectors return `false` in headless mode. YouTube Studio detects headless Chromium and either redirects or fails to render the page. Every selector tested — from basic (`input[type="file"]`) to complex (`ytcp-video-metadata-playlists`) — fails in headless.

| Selector | Headful | Headless |
|----------|---------|----------|
| `input[type="file"]` | ✓ | ✗ |
| `#title-textarea #textbox` | ✓ | ✗ |
| `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` | ✓ | ✗ |
| `tp-yt-iron-overlay-backdrop` | ✓ | ✗ |
| `ytcp-video-metadata-playlists` | ✓ | ✗ |
| `ytcp-dropdown-trigger[aria-label="Select playlists"]` | ✓ | ✗ |
| `ytcp-video-metadata-visibility` | ✓ | ✗ |
| `#save` | ✓ | ✗ |

**Implication**: The `headless = true` config option in yt-recorder will NOT work with current YouTube Studio. Upload automation REQUIRES headful mode.

### Edit Page Visibility Control

On the edit page (`/video/{id}/edit`), visibility is NOT controlled by radio buttons. Instead:
- Component: `ytcp-video-metadata-visibility`
- Trigger: `ytcp-icon-button#select-button[aria-label="Edit video visibility status"]`
- This is a dropdown/modal trigger, not inline radio buttons

The `tp-yt-paper-radio-button[name="PRIVATE"]` selector only applies within the **upload wizard** (step 4), NOT the edit page.

### Migration Status

- `tp-yt-*` components: 36 instances (declining — legacy)
- `ytcp-*` components: 293 instances (dominant — new)
- Radio buttons (`tp-yt-paper-radio-button`): Still using old prefix for audience/age settings
- Buttons/triggers: Fully migrated to `ytcp-button`, `ytcp-dropdown-trigger`
- Dialogs: Mix of `tp-yt-paper-dialog` (container) and `ytcp-*` (content)

### Done Button Text Change

The upload dialog's `#done-button` now displays **"Save"** instead of "Done". The `id` and selector are unchanged, but any assertions on button text should use "Save".

## Items Needing Re-verification

1. **Private Radio** (`tp-yt-paper-radio-button[name="PRIVATE"]`): Daily upload limit prevented reaching the visibility step. Based on migration patterns (other radios unchanged), this selector is **likely still valid** but needs confirmation when upload limit resets.
2. **Playlist Checkbox Interaction**: Channel has 0 playlists, so `tp-yt-paper-checkbox` items couldn't be verified for click behavior. Pattern is confirmed from DOM structure.
3. **Playlist Search Visibility**: Search bar (`#search-input`) exists but is hidden (`div#search[hidden]`) when no playlists exist. Needs verification with playlists present.

## Raw Inspection Data Files

- `upload-dom-inspection.json` — Pre-upload page DOM scan
- `upload-full-inspection.json` — Post-upload step-by-step inspection
- `edit-deep-inspection.json` — Edit page deep DOM + playlist dialog
- `final-inspection.json` — Headful vs headless comparison + page save state
- `upload-page.png` — Upload wizard step 1 (Details)
- `edit-page.png` — Video edit page
- `task-1-playlist-dialog.png` — Playlist dialog opened
