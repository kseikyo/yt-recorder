# yt-recorder (v0.2.0)

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
DISCOVERED → upload --keep → REGISTERED → status → transcribe → clean → TRANSCRIBED
```

1. **DISCOVERED**: File found in directory
2. **upload --keep**: Uploaded to all configured accounts (primary + mirrors) without deleting local files
3. **REGISTERED**: Entry created in `registry.md`
4. **status**: Verify upload success and transcript availability
5. **transcribe**: Fetch transcripts for uploaded videos
6. **clean**: Delete local files only after they are marked as `TRANSCRIBED` in the registry

### Transcript Status

The `transcribe` command tracks the state of each video's transcript:

- **PENDING**: Transcript not yet available (YouTube is still processing)
- **DONE**: Transcript successfully fetched and saved locally
- **UNAVAILABLE**: YouTube has no auto-captions for this video
- **ERROR**: Fetch failed (network issue, authentication error, etc.)

**Retry Behavior**: Running `transcribe --retry` will only attempt to fetch transcripts for videos currently in the **ERROR** state. PENDING and UNAVAILABLE states are skipped unless `--force` is used.

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

### `clean`

Delete local files that have been successfully uploaded and transcribed.

```bash
yt-recorder clean DIRECTORY [OPTIONS]
```

Options:
- `--dry-run`: Show which files would be deleted without actually deleting them

**Safety**: This command only deletes files that are explicitly marked as `status=TRANSCRIBED` in the registry.

### `health`

Verify that account credentials and authentication states are still valid.

```bash
yt-recorder health
```

**Output**: Shows which configured accounts are currently authenticated and ready for use.

## Security

⚠️ **Credential files grant full Google account access.**

See [SECURITY.md](SECURITY.md) for detailed security practices and vulnerability reporting.

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

yt-recorder follows a **Hexagonal Architecture** (Ports and Adapters) to ensure core logic remains isolated from external dependencies like YouTube's UI or the local filesystem.

```
      ┌─────────────────────────────────────────────────────────┐
      │                          CLI                            │
      │           (upload, transcribe, sync, status)            │
      └───────────────┬───────────────────────────┬─────────────┘
                      │                           │
      ┌───────────────▼───────────────────────────▼─────────────┐
      │                        Pipeline                         │
      │         (Orchestrates Upload → Registry → Clean)        │
      └───────────────┬───────────────────────────┬─────────────┘
                      │                           │
      ┌───────────────▼───────────────────────────▼─────────────┐
      │                        Adapters                         │
      │        (YouTubeAdapter, RAID, RegistryAdapter)          │
      └───────────────┬───────────────────────────┬─────────────┘
                      │                           │
      ┌───────────────▼───────────────────────────▼─────────────┐
      │                         Domain                          │
      │        (Models, Protocols: VideoUploader, etc.)         │
      └─────────────────────────────────────────────────────────┘
```

- **CLI**: Entry points using `click`.
- **Pipeline**: High-level orchestration of the video lifecycle.
- **Adapters**: Concrete implementations of domain protocols. `RAID` coordinates multiple `YouTubeAdapter` instances.
- **Domain**: Pure business logic, models (`RegistryEntry`, `TranscriptStatus`), and protocol definitions.
- **Sync Playwright**: Uses synchronous Playwright for predictable browser automation without `async/await` complexity.

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

**Issues welcome · PRs paused**

We are currently accepting bug reports and feature requests via GitHub Issues. However, as a solo-maintained project in active v0.2 development, **Pull Requests are currently paused** and will not be reviewed at this time. This allows us to focus on stabilizing the core architecture.

If you'd like to contribute:
1. Check existing issues or open a new one
2. Ensure `mypy --strict` and `ruff check` pass on your local changes
3. Run tests with `pytest --cov`

## License

MIT License - See LICENSE file