# yt-recorder

YouTube as organized private video storage. Upload recordings via Playwright browser automation, RAID-mirror across multiple accounts, extract transcripts.

## ⚠️ Disclaimer

**Use at your own risk.** This tool automates browser interactions with YouTube. While it operates within the same actions a user performs manually, browser automation may violate YouTube's Terms of Service. This tool is designed for personal use on your own accounts.

### Legal
- This tool does not circumvent DRM or access restrictions
- It automates actions the account owner can perform manually
- It does not scrape, redistribute, or download copyrighted content from others
- Users are responsible for compliance with YouTube's ToS and local laws
- The authors provide no warranty and accept no liability

## Installation

```bash
uv pip install -e .
playwright install chromium
```

> **Note**: `playwright install chromium` is needed for video uploads.
> The `setup` command uses your system's Chrome browser (not Playwright's Chromium)
> to bypass Google's automation detection during login.

## Quick Start

### 1. Set up your YouTube account

```bash
yt-recorder setup --account primary
```

This opens your system's Chrome browser for manual login. After successful login, credentials are saved securely.

### 2. (Optional) Add a backup account for RAID redundancy

```bash
yt-recorder setup --account backup
```

### 3. Configure settings

Edit `~/.config/yt-recorder/config.toml`:

```toml
[accounts]
primary = "/path/to/primary_storage_state.json"
backup = "/path/to/backup_storage_state.json"

[scanner]
extensions = [".mp4", ".mkv", ".mov", ".webm", ".avi"]
exclude_dirs = ["transcripts"]
max_depth = 1

[upload]
limit = 5
headless = true
```

### 4. Upload recordings

```bash
yt-recorder upload ~/recordings --limit 10
```

### 5. Fetch transcripts

```bash
yt-recorder transcribe ~/recordings
```

Or do both in one command:

```bash
yt-recorder sync ~/recordings --limit 5
```

## How It Works

### Folder → Playlist Mapping

```
recordings/
├── vid1.mp4              → playlist "recordings"
├── talks/
│   └── talk1.mp4         → playlist "talks"
└── ideas/
    └── idea1.mp4         → playlist "ideas"
```

### RAID-1 Mirroring

Every video is uploaded to multiple accounts for redundancy:
- **Primary account**: Used for transcript extraction
- **Mirror accounts**: Storage redundancy
- Any single account surviving = full data recovery

### Video Lifecycle

```
DISCOVERED → upload (×N accounts) → REGISTERED → delete local → transcript → TRANSCRIBED
```

1. File found in directory
2. Uploaded to all configured accounts (primary + mirrors)
3. Registered in `registry.md`
4. Local file deleted (if all uploads succeeded)
5. Transcript extracted (may take minutes to hours)

## Commands

### `upload`

Upload new recordings to YouTube.

```bash
yt-recorder upload DIRECTORY [OPTIONS]
```

Options:
- `--dry-run`: Show plan without uploading
- `--limit, -n`: Max files to upload
- `--account`: Upload to single account only
- `--keep`: Keep local files after upload
- `--retry-failed`: Retry failed mirror uploads
- `--verbose`: Show detailed progress and debug info

### `transcribe`

Fetch transcripts for uploaded videos.

```bash
yt-recorder transcribe DIRECTORY [OPTIONS]
```

Options:
- `--retry`: Retry previously failed transcripts
- `--force`: Overwrite existing transcripts

### `sync`

Upload + transcribe in one command.

```bash
yt-recorder sync DIRECTORY [OPTIONS]
```

Options:
- `--dry-run`: Show plan without uploading or transcribing
- `--limit, -n`: Max files to process
- `--verbose`: Show detailed progress and debug info

### `status`

Show upload and transcript status.

```bash
yt-recorder status DIRECTORY
```

## Security

⚠️ **Credential files grant full Google account access.**

After running `setup`, these files are created:
- `storage_state.json`: Playwright session (cookies, localStorage)
- `cookies.txt`: Netscape format cookies for yt-dlp

**Protections in place:**
- Files have `0600` permissions (owner read/write only)
- `.gitignore` automatically excludes credential files
- Config directory is XDG-compliant (`~/.config/yt-recorder/` on Linux)

**Never commit or share these files.** If compromised, revoke access via Google Account settings immediately.

## Risks & Limitations

| Risk | Mitigation |
|------|-----------|
| YouTube UI changes | Selectors isolated in `constants.py` |
| Bot detection | Per-action delays, headful mode for setup |
| Cookie expiry | Re-run `setup` when sessions expire |
| Large files (500MB+) | No resume on failure; browser handles natively |
| Account termination | RAID mirroring provides redundancy |

## Technical Details

### Architecture

- **Hexagonal architecture**: CLI → Pipeline → Adapters → Domain
- **Sync Playwright**: No async/await complexity
- **Protocol-based**: Easy to test, extend to other platforms

### Tools Used

- `playwright`: Browser automation for YouTube upload
- `yt-dlp`: Transcript extraction from private videos
- `click`: CLI framework
- `markdown`: Human-readable registry format

## Troubleshooting

### "Session expired" error

```bash
yt-recorder setup --account primary
```

### "YouTube UI may have changed" error

Update selectors in `src/yt_recorder/constants.py` or check for yt-recorder updates.

### "Google detected automation" error

Wait and retry later. Consider using `--no-headless` flag.

### Transcripts not available immediately

YouTube auto-captions take minutes to hours to process. Re-run `transcribe` later.

## Contributing

PRs welcome. Please ensure:
- `mypy --strict` passes
- `ruff check` passes
- Tests pass with `pytest --cov`

## License

MIT License - See LICENSE file