# Learnings — v0.2 Execution

## Codebase Patterns
- Python 3.9 target (no `match`, use `from __future__ import annotations`)
- Frozen dataclasses throughout (never mutate, create new instances)
- Hexagonal architecture: CLI → Pipeline → Adapters → Domain
- All YouTube selectors centralized in constants.py
- Registry: markdown table format (git-friendly, human-readable)
- Atomic writes: tempfile + os.replace pattern (see registry.py)

## Testing Conventions
- pytest + unittest.mock.Mock (auto-attributes)
- Adapters tested with mocked externals (Playwright, yt-dlp)
- Pipeline tested with mocked adapter protocols
- CLI tested with click.testing.CliRunner

## Commit Style
- Concise, sacrifice grammar
- Examples: "fix: upload flow — domcontentloaded, wait_for_function Done btn, dialog close"

## Chrome DevTools Protocol Security

**Fundamental Limitation**: Chrome with `--remote-debugging-port=` exposes full browser control via CDP to ANY local process. This includes:
- Reading all cookies (including Google session)
- Injecting JavaScript
- Exfiltrating sensitive data

**Attack Window**: Entire duration of manual login (30s to 5min).

**Mitigation Strategy**: 
- Random port selection reduces attack surface but doesn't eliminate risk
- Any local process can scan for and connect to CDP ports
- Perfect security requires Chrome remote debugging alternatives (none exist for cross-browser auth)
- Warning + immediate close recommendation reduces exposure window

**Implementation**: Added security warning to setup command output after port assignment, before user login prompt. Warning appears immediately after Chrome launches, alerting user to close Chrome immediately after login capture.

## Credential File Permissions (0o600) - COMPLETED

### Pattern Applied
Extended os.chmod(path, 0o600) pattern from cli.py setup to ALL credential writes:

1. **youtube.py:close()** - After Playwright storage_state write
   - Added: `os.chmod(str(self.account.storage_state), 0o600)` 
   - Ensures session cookies protected after browser context closes

2. **registry.py:_atomic_write()** - After tempfile creation
   - Added: `os.chmod(temp_path, 0o600)` immediately after mkstemp
   - Protects registry file before content write (prevents umask exposure)

3. **transcriber.py:extract_cookies()** - After cookies.txt write
   - Added: `os.chmod(str(cookies_txt_path), 0o600)` after file write
   - Ensures Netscape cookies file has strict permissions

### Test Fixes
- Patched os.chmod in test_youtube.py (2 tests) with `patch("os.chmod")`
- All 134 tests pass
- mypy --strict: Success (no issues)

### Security Rationale
Multi-user systems + backup tools may preserve default umask (0o644). Explicit chmod ensures credentials never readable by other users, even if:
- Backup software copies files
- Temp files created with default permissions
- Registry file rewritten during runtime

### Key Learning
Atomic write pattern (tempfile + os.replace) doesn't preserve permissions. Must chmod BEFORE os.replace to ensure atomicity + security.

## Log Injection Vulnerability Fix

**Issue**: f-string logger calls allow log injection if variables contain newlines/ANSI escapes. Malicious video titles could forge log entries or inject terminal escapes.

**Pattern**: Python logging best practice is lazy %-formatting, not f-strings:
- ✓ `logger.exception("Upload failed for %s", path)` — lazy, safe
- ✗ `logger.exception(f"Upload failed for {path}")` — eager, vulnerable

**Files Fixed**:
1. pipeline.py:150 → `logger.exception("Upload failed for %s", path)`
2. raid.py:99 → `logger.warning("Mirror %s failed: %s", mirror.name, e)`
3. youtube.py:221,229,237 → All converted to %-formatting

**Verification**:
- `grep -rn 'logger\.\(warning\|exception\|error\)(f"' src/` returns 0 matches ✓
- `mypy --strict src` passes ✓
- 132/134 tests pass (2 pre-existing failures from os.chmod in close()) ✓

**Key Insight**: Lazy formatting defers string interpolation to logging handler, preventing injection attacks. The logging module safely escapes variables at output time.

## Registry Batch Update + File Locking (W1.3) - COMPLETED

### Implementation
- `_locked()` context manager: fcntl.flock(LOCK_EX) on .lock file adjacent to registry.md
- `update_many(updates)`: single load → iterate + mutate → single _write_all()
- All mutators (append, update_transcript, update_account_id) wrapped with `_locked()`

### Typing Decision
- Plan specified `dict[str, dict[str, object]]` for update_many signature
- Used `dict[str, dict[str, Any]]` instead — `object` causes mypy --strict failures with RegistryEntry constructor (can't assign `object` to `bool`/`dict[str,str]` params)
- `Any` is correct here: values are dynamically typed field overrides

### Ruff Compliance
- `collections.abc.Iterator` preferred over `typing.Iterator` (UP035)
- Import block must be alphabetically sorted (I001)
- `SIM115` rule not enabled in project ruff config — no `noqa` needed for bare `open()`

### Performance Impact
- Before: 50 transcripts → 100 I/O ops (50 load + 50 write)
- After: 50 transcripts → 2 I/O ops (1 load + 1 write via update_many)
- Existing tests (18) pass unchanged — locking is transparent to existing callers

## TranscriptStatus Enum (W3.1) - COMPLETED

### Implementation
- Added `class TranscriptStatus(str, Enum)` with 4 states: PENDING, DONE, UNAVAILABLE, ERROR
- Changed `RegistryEntry.has_transcript: bool` → `transcript_status: TranscriptStatus`
- Added `@property has_transcript() -> bool` for backwards compatibility
- Returns `self.transcript_status == TranscriptStatus.DONE`

### Design Rationale
- `str, Enum` inheritance allows string serialization + `isinstance(TranscriptStatus.DONE, str)` = True
- Satisfies Protocol's `status: str` requirement
- Enables round-trip to/from registry markdown format
- UNAVAILABLE state fixes infinite retry bug (distinguishes from ERROR)

### Type Safety
- mypy --strict: 5 expected errors in registry.py + pipeline.py (W3.2 fixes these)
- models.py itself: fully typed, no errors
- Enum values: "pending", "done", "unavailable", "error"

### Backwards Compatibility
- `entry.has_transcript` property allows existing code to work during migration
- W3.2 will update registry format to use enum values
- W3.3 will update pipeline to use enum directly
