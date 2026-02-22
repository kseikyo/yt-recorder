# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it via [GitHub Security Advisories](https://github.com/kseikyo/yt-recorder/security/advisories/new).

DO NOT report security issues in public issues.

## What Data Leaves Your Machine

- **YouTube API calls** via authenticated browser session (upload, transcript fetch)
- **yt-dlp HTTP requests** for transcript downloads
- **No telemetry**, analytics, or phone-home to third parties

All data flows directly between your machine and YouTube/Google services.

## Credential Storage

yt-recorder stores authentication credentials locally:

- **storage_state.json**: Playwright browser session (cookies + localStorage)
- **cookies.txt**: Netscape format cookies for yt-dlp
- **Permissions**: `0o600` (owner read/write only) enforced on every write
- **Location**: `~/.config/yt-recorder/` (XDG-compliant)
- **Ignored**: `.gitignore` rules prevent accidental commits

### Credential Security Measures

1. **File permissions** automatically set to `0o600` on creation and update
2. **Atomic writes** with temp file + `os.replace` prevent corruption
3. **Setup command** warns about credential file locations and risks

## CDP Port Exposure During Setup

The `yt-recorder setup` command temporarily opens a Chrome DevTools Protocol debugging port to capture your authenticated session.

**Security implications:**
- Any local process can connect to this port while open
- Full browser control is possible during the login window
- Random port selection reduces (but doesn't eliminate) attack surface

**Mitigation:**
- Close Chrome immediately after login capture
- Setup window lasts only 30s-5min (manual login duration)
- Warning displayed before port opens

## Path Traversal Protection

Registry-derived file paths are validated using `safe_resolve()`:
- Blocks `../` traversal attempts
- Rejects absolute paths in relative contexts
- Prevents malicious registry entries from accessing files outside base directory

Example blocked path: `../../etc/passwd` → raises `ValueError`

## Log Sanitization

- **No sensitive data at INFO level**: video IDs, account names logged only at DEBUG
- **%-formatting prevents log injection**: `logger.info("Upload %s", file)` instead of f-strings
- **User-controlled data** never interpolated directly into format strings

## Threat Model

yt-recorder assumes:
- **Local machine is trusted** (you have physical access)
- **YouTube/Google are trusted** (you consent to upload data there)
- **Filesystem permissions are enforced** (OS-level access control works)

yt-recorder does NOT protect against:
- Malware with root/admin privileges on your machine
- Compromised YouTube/Google accounts (revoke via Google Account settings)
- Physical access attacks (full disk encryption is your responsibility)

## Security Best Practices

1. **Run `yt-recorder health`** regularly to check credential file permissions
2. **Rotate credentials** if storage_state.json is >7 days old (re-run `setup`)
3. **Use dedicated Google account** for recording (don't mix with personal email)
4. **Enable 2FA** on your YouTube account
5. **Review `.gitignore`** before committing to ensure credentials excluded

## Updates and Patching

- Security fixes released as patch versions (e.g., 0.2.1)
- Breaking security changes may require major version bump
- Check releases for `[SECURITY]` tag in commit messages
