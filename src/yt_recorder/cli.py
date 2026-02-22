"""Command-line interface for yt-recorder."""

from __future__ import annotations

import click
from pathlib import Path
from typing import Optional

from yt_recorder.utils import find_chrome


@click.group()
@click.version_option()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def main(verbose: bool) -> None:
    """YouTube recording and transcription pipeline."""
    import logging

    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


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
    limit: Optional[int],
    account: Optional[str],
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

    if report.errors:
        click.echo("\nErrors:")
        for error in report.errors:
            click.echo(f"  - {error}")


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

    if report.errors:
        click.echo("\nErrors:")
        for error in report.errors:
            click.echo(f"  - {error}")


@main.command()
@click.argument(
    "directory", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path)
)
@click.option("--dry-run", is_flag=True, help="Show plan without uploading")
@click.option("--limit", "-n", type=int, help="Max files to upload")
@click.option("--keep", is_flag=True, help="Keep local files after upload")
@click.option("--retry-failed", is_flag=True, help="Retry failed mirror uploads")
def sync(
    directory: Path, dry_run: bool, limit: Optional[int], keep: bool, retry_failed: bool
) -> None:
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
    from yt_recorder.config import load_config
    from yt_recorder.adapters.registry import MarkdownRegistryStore
    from yt_recorder.adapters.scanner import scan_recordings
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

    for path, playlist in files:
        rel_path = str(path.relative_to(directory))
        entry = entry_map.get(rel_path)

        if entry:
            uploaded += 1
            icon = _transcript_icon(entry.transcript_status.value)
            click.echo(f"  ✅ {rel_path} [{entry.transcript_status.value}] {icon}")
            if entry.has_transcript:
                transcribed += 1

            for account, video_id in entry.account_ids.items():
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
            for acct_name, video_id in entry.account_ids.items():
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

                context.storage_state(path=str(storage_state_path))
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
    actual_cookies = transcriber.extract_cookies(storage_state_path)
    shutil.copy2(actual_cookies, cookies_path)
    os.chmod(cookies_path, 0o600)

    config_path = config_dir / "config.toml"
    if not config_path.exists():
        save_config_template(config_path)

    config_lines = config_path.read_text().splitlines()

    account_exists = False
    new_lines = []
    for line in config_lines:
        stripped = line.strip()
        if stripped.startswith(f"{account} ") or stripped.startswith(f"{account}="):
            new_lines.append(f'{account} = "{storage_state_path}"')
            account_exists = True
        else:
            new_lines.append(line)

    if not account_exists:
        in_accounts = False
        inserted = False
        final_lines = []
        for line in new_lines:
            if line.strip() == "[accounts]":
                in_accounts = True
            elif line.strip().startswith("[") and line.strip() != "[accounts]":
                if in_accounts and not inserted:
                    final_lines.append(f'{account} = "{storage_state_path}"')
                    inserted = True
                in_accounts = False

            if (
                in_accounts
                and not inserted
                and (line.strip().startswith("#") or line.strip() == "")
            ):
                final_lines.append(f'{account} = "{storage_state_path}"')
                inserted = True

            final_lines.append(line)

        if not inserted:
            final_lines.append(f'{account} = "{storage_state_path}"')

        new_lines = final_lines

    config_path.write_text("\n".join(new_lines))

    gitignore_path = config_dir / ".gitignore"
    gitignore_content = "*_storage_state.json\n*_cookies.txt\nconfig.toml\n"
    gitignore_path.write_text(gitignore_content)

    click.echo(f"\n✅ Account '{account}' configured successfully!")
    click.echo(f"   Storage state: {storage_state_path}")
    click.echo(f"   Cookies: {cookies_path}")
    click.echo(f"\n⚠️  WARNING: These files grant full Google account access.")
    click.echo(f"   NEVER commit or share them!")
    click.echo(f"   They are in: {config_dir}")
    click.echo(f"\nNext steps:")
    click.echo(f"   1. Edit {config_path} to adjust settings if needed")
    click.echo(f"   2. Run: yt-recorder upload <directory>")


if __name__ == "__main__":
    main()
