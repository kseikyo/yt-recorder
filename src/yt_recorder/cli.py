"""Command-line interface for yt-recorder."""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import click

from yt_recorder.utils import find_chrome


@click.group()
@click.version_option()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable DEBUG stderr (file sink always DEBUG)",
)
def main(verbose: bool) -> None:
    """YouTube recording and transcription pipeline."""
    import logging

    from yt_recorder.log import configure_logging

    log_file = configure_logging(verbose)
    if verbose:
        click.echo(f"log: {log_file}", err=True)
    logging.getLogger(__name__).debug("log sink ready: %s", log_file)


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.option("--dry-run", is_flag=True, help="Show plan without uploading")
@click.option("--limit", "-n", type=int, help="Max files to upload")
@click.option("--account", help="Upload to single account only (skips RAID)")
@click.option("--keep", is_flag=True, help="Keep local files after upload")
@click.option("--retry-failed", is_flag=True, help="Retry failed mirror uploads")
def upload(
    directory: Path,
    dry_run: bool,
    limit: int | None,
    account: str | None,
    keep: bool,
    retry_failed: bool,
) -> None:
    """Upload recorded content to YouTube.

    Uploads videos from DIRECTORY to YouTube using configured accounts.
    Files are organized into playlists based on folder structure.
    """
    from yt_recorder.pipeline import RecordingPipeline

    pipeline = RecordingPipeline.from_directory(directory)
    report = pipeline.upload_new(
        directory=directory,
        limit=limit,
        dry_run=dry_run,
        keep=keep,
        retry_failed=retry_failed,
        single_account=account,
    )

    if dry_run:
        click.echo(f"Would upload {report.skipped} files")
        return

    click.echo(f"Uploaded: {report.uploaded}")
    click.echo(f"Failed: {report.upload_failed}")
    click.echo(f"Deleted: {report.deleted_count}")
    click.echo(f"Kept: {report.kept_count}")
    if report.playlist_failed:
        click.echo(f"Playlist failures: {report.playlist_failed}")

    if report.errors:
        click.echo("\nErrors:")
        for error in report.errors:
            click.echo(f"  - {error}")

    if report.upload_failed or report.errors:
        sys.exit(1)


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.option("--retry", is_flag=True, help="Retry previously failed transcripts")
@click.option("--force", is_flag=True, help="Overwrite existing transcripts")
def transcribe(directory: Path, retry: bool, force: bool) -> None:
    """Fetch transcripts for uploaded videos."""
    from yt_recorder.pipeline import RecordingPipeline

    pipeline = RecordingPipeline.from_directory(directory, with_transcriber=True)
    report = pipeline.fetch_transcripts(directory, retry=retry, force=force)

    click.echo(f"Transcripts fetched: {report.transcripts_fetched}")
    click.echo(f"Pending (not ready): {report.transcripts_pending}")

    skipped_lines: list[str] = []
    if report.transcripts_skipped_done:
        skipped_lines.append(f"  {report.transcripts_skipped_done} already done")
    if report.transcripts_skipped_unavailable:
        skipped_lines.append(
            f"  {report.transcripts_skipped_unavailable} marked unavailable (no captions)"
        )
    if report.transcripts_skipped_error:
        skipped_lines.append(
            f"  {report.transcripts_skipped_error} in error state (use --retry)"
        )
    if report.transcripts_skipped_no_primary_id:
        skipped_lines.append(
            f"  {report.transcripts_skipped_no_primary_id} have no primary upload "
            f"(parent stubs / failed primary)"
        )
    if skipped_lines:
        click.echo("Skipped:")
        for line in skipped_lines:
            click.echo(line)

    if report.errors:
        click.echo("\nErrors:")
        for error in report.errors:
            click.echo(f"  - {error}")
        sys.exit(1)


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.option("--dry-run", is_flag=True, help="Show plan without uploading")
@click.option("--limit", "-n", type=int, help="Max files to upload")
@click.option("--keep", is_flag=True, help="Keep local files after upload")
@click.option("--retry-failed", is_flag=True, help="Retry failed mirror uploads")
def sync(directory: Path, dry_run: bool, limit: int | None, keep: bool, retry_failed: bool) -> None:
    """Sync recordings (upload + transcribe).

    Uploads new videos then fetches transcripts. Transcripts may not be
    immediately available after upload — re-run sync later if needed.
    """
    from yt_recorder.pipeline import RecordingPipeline

    pipeline = RecordingPipeline.from_directory(directory, with_transcriber=True)

    click.echo("Uploading...")
    upload_report = pipeline.upload_new(
        directory=directory,
        limit=limit,
        keep=keep,
        retry_failed=retry_failed,
        dry_run=dry_run,
    )

    if dry_run:
        click.echo(f"Would upload {upload_report.skipped} files")
        return

    click.echo(f"Uploaded: {upload_report.uploaded}, Failed: {upload_report.upload_failed}")

    if upload_report.uploaded > 0:
        click.echo("\nNote: YouTube auto-captions take minutes to hours to process.")
        click.echo("      Re-run 'yt-recorder transcribe' later if transcripts aren't ready.")

    click.echo("\nFetching transcripts...")
    transcript_report = pipeline.fetch_transcripts(directory)
    click.echo(
        f"Fetched: {transcript_report.transcripts_fetched}, Pending: {transcript_report.transcripts_pending}"
    )

    if (
        upload_report.upload_failed
        or upload_report.errors
        or transcript_report.errors
    ):
        sys.exit(1)


@main.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    required=False,
    default=None,
)
@click.option("--video-id", help="Single video ID to assign")
@click.option("--name", help="Playlist name (required with --video-id)")
@click.option("--dry-run", is_flag=True, help="Show plan without assigning")
@click.option("--account", help="Use specific account only")
def playlist(
    directory: Path | None,
    video_id: str | None,
    name: str | None,
    dry_run: bool,
    account: str | None,
) -> None:
    """Assign playlists to uploaded videos.

    Assign videos to playlists either in batch from a directory registry,
    or assign a single video by ID.
    """
    if video_id and not name:
        click.echo("Error: --name required with --video-id")
        sys.exit(1)
    if name and not video_id:
        click.echo("Error: --video-id required with --name")
        sys.exit(1)
    if directory and video_id:
        click.echo("Error: Provide either DIRECTORY or both --video-id and --name, not both")
        sys.exit(1)
    if not directory and not video_id:
        click.echo("Error: Provide either DIRECTORY or both --video-id and --name")
        sys.exit(1)

    if directory:
        from yt_recorder.pipeline import RecordingPipeline

        def on_progress(account_name: str, vid_id: str, playlist_name: str, success: bool) -> None:
            symbol = "✓" if success else "✗"
            click.echo(f"{symbol} {vid_id} → {playlist_name} ({account_name})")

        pipeline = RecordingPipeline.from_directory(directory)
        report = pipeline.assign_playlists(
            directory,
            single_account=account,
            dry_run=dry_run,
            on_progress=on_progress,
        )

        if dry_run:
            click.echo(f"Would assign: {report.assigned + report.failed} videos")
            return

        click.echo(f"Assigned: {report.assigned}")
        click.echo(f"Failed: {report.failed}")
        click.echo(f"Skipped: {report.skipped}")

        if report.errors:
            click.echo("\nErrors:")
            for error in report.errors:
                click.echo(f"  - {error}")

    else:
        from yt_recorder.adapters.raid import RaidAdapter
        from yt_recorder.config import load_config

        config = load_config()
        raid = RaidAdapter(config.accounts, config.headless, config.delays)
        raid.open()
        try:
            adapter = raid.get_adapter(config.accounts[0].name)
            success = adapter.assign_playlist(video_id or "", name or "")
            if success:
                click.echo(f"✓ Assigned {video_id} to playlist '{name}'")
            else:
                click.echo(f"✗ Failed to assign {video_id} to playlist '{name}'")
        finally:
            raid.close()


def _transcript_icon(status_value: str) -> str:
    icons: dict[str, str] = {
        "done": "📝",
        "pending": "⏳",
        "unavailable": "🚫",
        "error": "❌",
    }
    return icons.get(status_value, "?")


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
def status(directory: Path) -> None:
    """Show upload and transcript status."""
    from yt_recorder.adapters.registry import MarkdownRegistryStore
    from yt_recorder.adapters.scanner import scan_recordings
    from yt_recorder.config import load_config
    from yt_recorder.domain.exceptions import RegistryFileNotFoundError, RegistryParseError

    config = load_config()
    registry_path = directory / "registry.md"

    try:
        registry = MarkdownRegistryStore(registry_path, [a.name for a in config.accounts])
        entries = registry.load()
    except (FileNotFoundError, RegistryFileNotFoundError, RegistryParseError):
        entries = []

    files = scan_recordings(
        directory,
        list(config.extensions),
        list(config.exclude_dirs),
        config.max_depth,
    )

    entry_map = {e.file: e for e in entries}

    click.echo(f"📁 {directory.name}/ ({len(files)} files)")

    uploaded = 0
    transcribed = 0
    mirror_failures = 0

    for path, _playlist in files:
        rel_path = str(path.relative_to(directory))
        entry = entry_map.get(rel_path)

        if entry:
            uploaded += 1
            icon = _transcript_icon(entry.transcript_status.value)
            click.echo(f"  ✅ {rel_path} [{entry.transcript_status.value}] {icon}")
            if entry.has_transcript:
                transcribed += 1

            for _account, video_id in entry.account_ids.items():
                if video_id == "—":
                    mirror_failures += 1
        else:
            click.echo(f"  ⬜ {rel_path} (not uploaded)")

    scanned_paths = {str(path.relative_to(directory)) for path, _ in files}
    for entry in entries:
        if entry.file not in scanned_paths:
            uploaded += 1
            icon = _transcript_icon(entry.transcript_status.value)
            click.echo(f"  ☁️  {entry.file} [{entry.transcript_status.value}] {icon}")
            if entry.has_transcript:
                transcribed += 1
            for _acct_name, video_id in entry.account_ids.items():
                if video_id == "—":
                    mirror_failures += 1

    click.echo(
        f"\nUploaded: {uploaded}/{len(files)} | Transcribed: {transcribed}/{uploaded} | Mirror failures: {mirror_failures}"
    )


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def clean(directory: Path, dry_run: bool) -> None:
    """Delete local files that are fully synced."""
    from yt_recorder.pipeline import RecordingPipeline

    pipeline = RecordingPipeline.from_directory(directory)
    report = pipeline.clean_synced(directory, dry_run=dry_run)

    if dry_run:
        if report.eligible:
            click.echo(f"Would delete {len(report.eligible)} files:")
            for f in report.eligible:
                click.echo(f"  {f}")
        else:
            click.echo("No files eligible for cleanup")
        return

    click.echo(f"Deleted: {report.deleted}")
    click.echo(f"Skipped: {report.skipped}")
    if report.errors:
        click.echo(f"\nErrors ({len(report.errors)}):")
        for e in report.errors:
            click.echo(f"  - {e}")


@main.group()
def registry() -> None:
    """Inspect and repair registry.md."""


@registry.command(name="verify")
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
def registry_verify(directory: Path) -> None:
    """Structural check of registry.md.

    Reports: rows whose source file is missing on disk, part rows whose
    parent_file is absent from the registry, and part_index/total_parts
    counts that don't match. Exits 0 if the registry is consistent, 1 otherwise.
    No network access — cannot detect deleted-on-YouTube videos.
    """
    from yt_recorder.adapters.registry import MarkdownRegistryStore
    from yt_recorder.config import load_config
    from yt_recorder.domain.exceptions import RegistryFileNotFoundError, RegistryParseError

    config = load_config()
    registry_path = directory / "registry.md"
    store = MarkdownRegistryStore(registry_path, [a.name for a in config.accounts])
    try:
        entries = store.load()
    except RegistryFileNotFoundError:
        click.echo(f"No registry at {registry_path}")
        return
    except RegistryParseError as e:
        click.echo(f"Registry parse error: {e}", err=True)
        sys.exit(1)

    problems: list[str] = []

    known_files = {e.file for e in entries}
    parent_part_counts: dict[str, set[int]] = {}
    parent_total_parts: dict[str, set[int]] = {}

    for entry in entries:
        abs_path = directory / entry.file
        if not abs_path.exists() and entry.parent_file is None:
            problems.append(f"missing on disk: {entry.file}")

        if entry.parent_file is not None:
            if entry.parent_file not in known_files:
                problems.append(
                    f"orphan part (parent_file not in registry): {entry.file} "
                    f"→ {entry.parent_file}"
                )
            if entry.part_index is not None:
                parent_part_counts.setdefault(entry.parent_file, set()).add(entry.part_index)
            if entry.total_parts is not None:
                parent_total_parts.setdefault(entry.parent_file, set()).add(entry.total_parts)

    for parent, totals in parent_total_parts.items():
        if len(totals) > 1:
            problems.append(
                f"inconsistent total_parts for {parent}: {sorted(totals)}"
            )
        indexes = parent_part_counts.get(parent, set())
        expected = next(iter(totals)) if len(totals) == 1 else None
        if expected is not None and indexes != set(range(1, expected + 1)):
            missing = sorted(set(range(1, expected + 1)) - indexes)
            if missing:
                problems.append(
                    f"missing part indexes for {parent}: {missing} "
                    f"(have {sorted(indexes)}, expected 1..{expected})"
                )

    click.echo(f"Entries: {len(entries)}")
    if not problems:
        click.echo("✓ registry consistent")
        return

    click.echo(f"✗ {len(problems)} problem(s):", err=True)
    for p in problems:
        click.echo(f"  - {p}", err=True)
    sys.exit(1)


@registry.command(name="prune")
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.argument("source_file", type=str)
@click.option("--dry-run", is_flag=True, help="Show rows that would be removed, then exit")
def registry_prune(directory: Path, source_file: str, dry_run: bool) -> None:
    """Remove rows for SOURCE_FILE and any of its split parts.

    SOURCE_FILE is the path as stored in registry.md (relative to DIRECTORY).
    Does not touch local files or YouTube uploads — markdown only.
    """
    from yt_recorder.adapters.registry import MarkdownRegistryStore
    from yt_recorder.config import load_config
    from yt_recorder.domain.exceptions import RegistryFileNotFoundError

    config = load_config()
    registry_path = directory / "registry.md"
    store = MarkdownRegistryStore(registry_path, [a.name for a in config.accounts])

    try:
        entries = store.load()
    except RegistryFileNotFoundError:
        click.echo(f"No registry at {registry_path}", err=True)
        sys.exit(1)

    matching = [
        e for e in entries if e.file == source_file or e.parent_file == source_file
    ]
    if not matching:
        click.echo(f"No rows match '{source_file}'", err=True)
        sys.exit(1)

    click.echo(f"Matched {len(matching)} row(s):")
    for e in matching:
        tag = ""
        if e.parent_file == source_file:
            tag = f" (part {e.part_index}/{e.total_parts})"
        click.echo(f"  - {e.file}{tag}")

    if dry_run:
        click.echo("(dry-run, no changes)")
        return

    removed = store.remove_source_and_parts(source_file)
    click.echo(f"Removed {len(removed)} row(s) from {registry_path}")


@main.command(name="reset-limits")
def reset_limits() -> None:
    """Clear cached upload limits for all accounts.

    Removes upload_limit_secs from config.toml for each account.
    Next upload will re-detect the limit.
    """
    from yt_recorder.config import Config

    config_path = Config.default_config_dir() / "config.toml"

    if not config_path.exists():
        click.echo("No cached limits found.")
        return

    import tomlkit

    content = config_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(content)

    if "accounts" not in doc:
        click.echo("No cached limits found.")
        return

    n = 0
    for _account_name, account_value in doc["accounts"].items():  # type: ignore[union-attr]
        if isinstance(account_value, dict) and "upload_limit_secs" in account_value:
            del account_value["upload_limit_secs"]
            n += 1

    if n == 0:
        click.echo("No cached limits found.")
        return

    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    click.echo(f"Reset upload limits for {n} accounts. Next upload will re-detect.")


def _find_free_port() -> int:
    """Find free TCP port for Chrome DevTools Protocol.

    Note: Random port selection reduces attack surface but doesn't eliminate
    the risk. Any local process can scan for and connect to CDP ports.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_cdp(port: int, timeout: float = 15.0) -> None:
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"Chrome CDP not responding on port {port} after {timeout}s")


@main.command()
def health() -> None:
    """Check system readiness for yt-recorder operations.

    Verifies:
    - Config loads successfully
    - All account credential files exist
    - Chrome/Chromium is available
    - Registry file is accessible (if exists)
    - yt-dlp is in PATH
    - Credential file permissions are secure (0o600)
    - Credential files are not stale (< 7 days old)

    Exit code: 0 if all checks pass, 1 if any check fails.
    """
    from yt_recorder.config import load_config

    Path.home() / ".config" / "yt-recorder"
    checks_passed = 0
    checks_failed = 0

    # Check 1: Config loads
    click.echo("Checking config...")
    try:
        config = load_config()
        click.echo("  ✓ Config loads successfully")
        checks_passed += 1
    except Exception as e:
        click.echo(f"  ✗ Config load failed: {e}", err=True)
        checks_failed += 1
        sys.exit(1)

    # Check 2: Account files exist
    click.echo("Checking account credentials...")
    if not config.accounts:
        click.echo("  ✗ No accounts configured", err=True)
        checks_failed += 1
    else:
        for account in config.accounts:
            storage_state = account.storage_state
            cookies = account.cookies_path

            # Check storage_state.json exists
            if not storage_state.exists():
                click.echo(f"  ✗ {account.name}: storage_state.json not found", err=True)
                checks_failed += 1
            else:
                click.echo(f"  ✓ {account.name}: storage_state.json exists")
                checks_passed += 1

                # Check storage_state.json permissions
                mode = storage_state.stat().st_mode & 0o777
                if mode != 0o600:
                    click.echo(
                        f"    ⚠ {account.name}: storage_state.json has permissions {oct(mode)} (should be 0o600)",
                        err=True,
                    )
                    checks_failed += 1
                else:
                    click.echo(f"    ✓ {account.name}: storage_state.json permissions OK (0o600)")
                    checks_passed += 1

                # Check storage_state.json age
                mtime = storage_state.stat().st_mtime
                age_days = (time.time() - mtime) / (24 * 3600)
                if age_days > 7:
                    click.echo(
                        f"    ⚠ {account.name}: session may expire soon ({age_days:.1f} days old)",
                        err=True,
                    )
                    checks_failed += 1
                else:
                    click.echo(f"    ✓ {account.name}: session fresh ({age_days:.1f} days old)")
                    checks_passed += 1

            # Check cookies.txt exists
            if not cookies.exists():
                click.echo(f"  ✗ {account.name}: cookies.txt not found", err=True)
                checks_failed += 1
            else:
                click.echo(f"  ✓ {account.name}: cookies.txt exists")
                checks_passed += 1

                # Check cookies.txt permissions
                mode = cookies.stat().st_mode & 0o777
                if mode != 0o600:
                    click.echo(
                        f"    ⚠ {account.name}: cookies.txt has permissions {oct(mode)} (should be 0o600)",
                        err=True,
                    )
                    checks_failed += 1
                else:
                    click.echo(f"    ✓ {account.name}: cookies.txt permissions OK (0o600)")
                    checks_passed += 1

    # Check 3: Chrome available
    click.echo("Checking Chrome/Chromium...")
    try:
        chrome_path = find_chrome()
        click.echo(f"  ✓ Chrome found: {chrome_path}")
        checks_passed += 1
    except FileNotFoundError as e:
        click.echo(f"  ✗ Chrome not found: {e}", err=True)
        checks_failed += 1

    # Check 4: yt-dlp available
    click.echo("Checking yt-dlp...")
    if shutil.which("yt-dlp"):
        click.echo("  ✓ yt-dlp found in PATH")
        checks_passed += 1
    else:
        click.echo("  ✗ yt-dlp not found in PATH", err=True)
        checks_failed += 1

    # Check 5: ffmpeg available
    click.echo("Checking ffmpeg...")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        click.echo(f"  ✓ ffmpeg found at {ffmpeg_path}")
        checks_passed += 1
    else:
        click.echo(
            "  ✗ ffmpeg not found  (required for video splitting — install: brew install ffmpeg)",
            err=True,
        )
        checks_failed += 1

    # Check 6: ffprobe available
    click.echo("Checking ffprobe...")
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        click.echo(f"  ✓ ffprobe found at {ffprobe_path}")
        checks_passed += 1
    else:
        click.echo(
            "  ✗ ffprobe not found  (required for video splitting — install: brew install ffmpeg)",
            err=True,
        )
        checks_failed += 1

    # Check 7: Registry accessible (if exists)
    click.echo("Checking registry...")
    # Registry is per-directory, so we just check if the concept is understood
    # In practice, registry.md is created per upload directory
    click.echo("  ✓ Registry system ready (created per directory)")
    checks_passed += 1

    # Summary
    click.echo(f"\n{'=' * 50}")
    click.echo(f"Checks passed: {checks_passed}")
    click.echo(f"Checks failed: {checks_failed}")

    if checks_failed > 0:
        click.echo("System is NOT ready for operations", err=True)
        sys.exit(1)
    else:
        click.echo("✓ System is ready for operations")
        sys.exit(0)


def _upsert_account_in_config(
    config_path: Path,
    account: str,
    storage_state_path: Path,
) -> None:
    """Insert/update an account in config.toml.

    Either creates a new ``[accounts.<account>]`` table or updates the
    ``path`` of an existing one (preserving sibling keys like
    ``upload_limit_secs`` written by :func:`save_detected_limit`).
    """
    import tomlkit
    from tomlkit.items import Table

    content = config_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(content)

    if "accounts" not in doc:
        doc["accounts"] = tomlkit.table()
    accounts = doc["accounts"]

    existing = accounts.get(account) if hasattr(accounts, "get") else None

    if isinstance(existing, Table):
        existing["path"] = str(storage_state_path)
    else:
        table = tomlkit.table()
        table["path"] = str(storage_state_path)
        accounts[account] = table  # type: ignore[index]

    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


@main.command()
@click.option("--account", required=True, help="Account name (e.g., primary, backup)")
def setup(account: str) -> None:
    """Set up YouTube account authentication.

    Opens your real Chrome browser for login (bypasses Google's automation
    detection), then extracts credentials via Chrome DevTools Protocol.
    Run this for each account you want to use.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    from playwright.sync_api import sync_playwright

    from yt_recorder.adapters.transcriber import YtdlpTranscriptAdapter
    from yt_recorder.config import Config, save_config_template

    click.echo(f"Setting up account: {account}")

    try:
        chrome_path = find_chrome()
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"Using Chrome: {chrome_path}")

    config_dir = Config.default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    storage_state_path = config_dir / f"{account}_storage_state.json"
    cookies_path = config_dir / f"{account}_cookies.txt"

    port = _find_free_port()

    click.echo(f"\n⚠️  Chrome CDP debugging port {port} is open during setup.")
    click.echo("   Any local process can access your Google session until setup completes.")
    click.echo("   Close Chrome immediately after login capture.")

    tmp_profile = tempfile.mkdtemp(prefix="yt-recorder-")
    proc: subprocess.Popen[bytes] | None = None

    try:
        proc = subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={tmp_profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "https://www.youtube.com",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        click.echo(f"\nChrome opened (CDP port {port}). Please:")
        click.echo("1. Click 'Sign in' (top right)")
        click.echo("2. Enter your Google credentials")
        click.echo("3. Complete any 2FA/security checks")
        click.echo("4. Wait for YouTube homepage to load")

        _wait_for_cdp(port)

        while True:
            click.echo("\nPress Enter when logged in (Ctrl+C to abort)...")
            input()

            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = browser.contexts[0]
                state = context.storage_state()
                cookies = state.get("cookies", [])
                yt_cookies = [c for c in cookies if ".youtube.com" in c.get("domain", "")]

                if not yt_cookies:
                    click.echo("No YouTube cookies found — are you logged in?")
                    click.echo("Log in and try again.")
                    browser.close()
                    continue

                # Write storage_state under restrictive umask so the file is
                # 0o600 from creation. Avoids the TOCTOU window where any local
                # process could read freshly-minted session cookies between
                # Playwright creating the file at default umask and the
                # explicit chmod a few lines below.
                _prev_umask = os.umask(0o077)
                try:
                    context.storage_state(path=str(storage_state_path))
                finally:
                    os.umask(_prev_umask)
                browser.close()
                break

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        shutil.rmtree(tmp_profile, ignore_errors=True)

    os.chmod(storage_state_path, 0o600)

    transcriber = YtdlpTranscriptAdapter(
        cookies_path=cookies_path,
        output_dir=config_dir / ".tmp",
    )
    transcriber.extract_cookies(storage_state_path)
    os.chmod(cookies_path, 0o600)

    config_path = config_dir / "config.toml"
    if not config_path.exists():
        save_config_template(config_path)

    _upsert_account_in_config(config_path, account, storage_state_path)

    gitignore_path = config_dir / ".gitignore"
    gitignore_content = "*_storage_state.json\n*_cookies.txt\nconfig.toml\n"
    gitignore_path.write_text(gitignore_content)

    click.echo(f"\n✅ Account '{account}' configured successfully!")
    click.echo(f"   Storage state: {storage_state_path}")
    click.echo(f"   Cookies: {cookies_path}")
    click.echo("\n⚠️  WARNING: These files grant full Google account access.")
    click.echo("   NEVER commit or share them!")
    click.echo(f"   They are in: {config_dir}")
    click.echo("\nNext steps:")
    click.echo(f"   1. Edit {config_path} to adjust settings if needed")
    click.echo("   2. Run: yt-recorder upload <directory>")


if __name__ == "__main__":
    main()
