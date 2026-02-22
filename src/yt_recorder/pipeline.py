from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from time import sleep
from typing import Callable, Optional

from yt_recorder.config import Config, load_config
from yt_recorder.domain.formatters import title_from_filename, format_transcript_md, parse_srt
from yt_recorder.domain.models import (
    RegistryEntry,
    SyncReport,
    TranscriptStatus,
    UploadResult,
    CleanReport,
)
from yt_recorder.domain.exceptions import (
    RegistryFileNotFoundError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
)
from yt_recorder.adapters.registry import MarkdownRegistryStore
from yt_recorder.adapters.scanner import scan_recordings
from yt_recorder.adapters.raid import RaidAdapter
from yt_recorder.adapters.transcriber import YtdlpTranscriptAdapter
from yt_recorder.domain.protocols import RegistryStore, TranscriptFetcher
from yt_recorder.utils import safe_resolve

logger = logging.getLogger(__name__)


class RecordingPipeline:
    """Orchestrates upload and transcription workflows."""

    def __init__(
        self,
        config: Config,
        registry: RegistryStore,
        raid: RaidAdapter,
        transcriber: TranscriptFetcher | None = None,
    ):
        self.config = config
        self.registry = registry
        self.raid = raid
        self.transcriber = transcriber

    @classmethod
    def from_directory(cls, directory: Path, with_transcriber: bool = False) -> RecordingPipeline:
        config = load_config()
        account_names = [a.name for a in config.accounts]
        registry = MarkdownRegistryStore(directory / "registry.md", account_names)
        raid = RaidAdapter(config.accounts, config.headless, config.delays)
        transcriber = None
        if with_transcriber and config.accounts:
            transcriber = YtdlpTranscriptAdapter(
                cookies_path=config.accounts[0].cookies_path,
                output_dir=directory / ".tmp",
            )
            transcriber.extract_cookies(config.accounts[0].storage_state)
        return cls(config, registry, raid, transcriber)

    def upload_new(
        self,
        directory: Path,
        limit: int | None = None,
        dry_run: bool = False,
        keep: bool = False,
        retry_failed: bool = False,
        single_account: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> SyncReport:
        """Upload new recordings to YouTube."""
        uploaded = 0
        skipped = 0
        upload_failed = 0
        deleted_count = 0
        kept_count = 0
        delete_failed = 0
        errors = []

        files = scan_recordings(
            directory,
            list(self.config.extensions),
            list(self.config.exclude_dirs),
            self.config.max_depth,
        )

        try:
            entries = self.registry.load()
        except RegistryFileNotFoundError:
            entries = []
        registered_files = {e.file for e in entries}

        files_to_process = [
            (path, playlist)
            for path, playlist in files
            if str(path.relative_to(directory)) not in registered_files
        ]

        if limit:
            files_to_process = files_to_process[:limit]

        if dry_run:
            return SyncReport(
                skipped=len(files_to_process),
                total_registered=len(entries),
            )

        if not files_to_process and not retry_failed:
            return SyncReport(total_registered=len(entries))

        self.raid.open()

        try:
            for idx, (path, playlist) in enumerate(files_to_process):
                if progress_callback:
                    progress_callback(idx + 1, len(files_to_process), path.name)
                try:
                    title = title_from_filename(path.name)

                    if single_account:
                        adapter = self.raid.get_adapter(single_account)
                        result = adapter.upload(path, title)
                        results: dict[str, Optional[UploadResult]] = {single_account: result}
                        adapter.assign_playlist(result.video_id, playlist)
                    else:
                        results = self.raid.upload(path, title, playlist)

                    all_succeeded = all(r is not None for r in results.values())

                    entry = RegistryEntry(
                        file=str(path.relative_to(directory)),
                        playlist=playlist,
                        uploaded_date=date.today(),
                        transcript_status=TranscriptStatus.PENDING,
                        account_ids={
                            name: (r.video_id if r else "—") for name, r in results.items()
                        },
                    )
                    self.registry.append(entry)
                    uploaded += 1

                    if all_succeeded and not keep and not single_account:
                        try:
                            path.unlink()
                            deleted_count += 1
                        except OSError as e:
                            errors.append(f"Failed to delete {path}: {e}")
                            delete_failed += 1
                    else:
                        kept_count += 1

                except Exception as e:
                    errors.append(f"Failed to upload {path}: {e}")
                    upload_failed += 1
                    logger.exception("Upload failed for %s", path)

            if retry_failed:
                for entry in entries:
                    failed_accounts = [
                        name for name, vid in entry.account_ids.items() if vid == "—"
                    ]
                    if not failed_accounts:
                        continue
                    file_path = directory / entry.file
                    if not file_path.exists():
                        errors.append(
                            f"Cannot retry {entry.file}: file not found (already deleted)"
                        )
                        continue
                    title = title_from_filename(file_path.name)
                    for acct_name in failed_accounts:
                        try:
                            retry_adapter = self.raid._adapters.get(acct_name)
                            if not retry_adapter:
                                continue
                            result = retry_adapter.upload(file_path, title)
                            if result:
                                retry_adapter.assign_playlist(
                                    result.video_id,
                                    entry.playlist,
                                )
                                self.registry.update_account_id(
                                    entry.file,
                                    acct_name,
                                    result.video_id,
                                )
                                uploaded += 1
                        except Exception as e:
                            errors.append(f"Retry failed for {entry.file} on {acct_name}: {e}")
                            upload_failed += 1

        finally:
            self.raid.close()

        return SyncReport(
            uploaded=uploaded,
            skipped=skipped,
            upload_failed=upload_failed,
            deleted_count=deleted_count,
            kept_count=kept_count,
            delete_failed=delete_failed,
            total_registered=len(entries) + uploaded,
            errors=errors,
        )

    def fetch_transcripts(
        self,
        directory: Path,
        retry: bool = False,
        force: bool = False,
    ) -> SyncReport:
        """Fetch transcripts for uploaded videos.

        Args:
            directory: Recordings directory
            retry: Retry previously ERROR transcripts
            force: Overwrite existing transcripts (all states)

        Returns:
            SyncReport with transcript statistics
        """
        if not self.transcriber:
            return SyncReport(errors=["Transcriber not initialized"])

        fetched = 0
        pending = 0
        errors: list[str] = []

        primary_account = next(
            (a for a in self.config.accounts if a.role == "primary"),
            None,
        )
        if not primary_account:
            return SyncReport(errors=["No primary account configured"])

        primary_name = primary_account.name

        try:
            entries = self.registry.load()
        except RegistryFileNotFoundError:
            entries = []

        retryable: set[TranscriptStatus] = {TranscriptStatus.PENDING}
        if retry:
            retryable.add(TranscriptStatus.ERROR)

        entries_needing = [
            e
            for e in entries
            if (force or e.transcript_status in retryable)
            and e.account_ids.get(primary_name)
            and e.account_ids[primary_name] != "—"
        ]

        if not entries_needing:
            return SyncReport(transcripts_fetched=0, transcripts_pending=0)

        # Collect results — don't update registry per-entry
        results: dict[str, TranscriptStatus] = {}

        for entry in entries_needing:
            try:
                video_id = entry.account_ids[primary_name]

                # Save to transcripts/{subdir}/{name}.md
                transcript_path = directory / "transcripts" / Path(entry.file).with_suffix(".md")
                transcript_path.parent.mkdir(parents=True, exist_ok=True)

                if transcript_path.exists() and not force:
                    continue

                # Fetch transcript
                srt_path = self.transcriber.fetch(video_id, self.config.transcript_language)

                # Parse SRT
                srt_content = srt_path.read_text()
                segments = parse_srt(srt_content)

                # Format markdown
                video_url = f"https://youtu.be/{video_id}"
                md_content = format_transcript_md(segments, video_url, entry.file)

                transcript_path.write_text(md_content)
                results[entry.file] = TranscriptStatus.DONE
                fetched += 1

                # Rate limiting
                sleep(self.config.transcript_delay)

            except TranscriptNotReadyError:
                pending += 1
                # stays PENDING — not in results
            except TranscriptUnavailableError:
                results[entry.file] = TranscriptStatus.UNAVAILABLE
                errors.append(f"No transcript available for {entry.file}")
            except Exception as e:
                results[entry.file] = TranscriptStatus.ERROR
                errors.append(f"Failed to fetch transcript for {entry.file}: {e}")

        if results:
            self.registry.update_many(
                {f: {"transcript_status": status} for f, status in results.items()}
            )

        return SyncReport(
            transcripts_fetched=fetched,
            transcripts_pending=pending,
            errors=errors,
        )

    def clean_synced(self, directory: Path, dry_run: bool = False) -> CleanReport:
        """Delete local files fully synced (all accounts + terminal transcript status)."""
        try:
            entries = self.registry.load()
        except RegistryFileNotFoundError:
            return CleanReport()

        terminal = {TranscriptStatus.DONE, TranscriptStatus.UNAVAILABLE}
        account_names = [a.name for a in self.config.accounts]
        deleted = 0
        skipped = 0
        errors: list[str] = []
        eligible: list[str] = []

        for entry in entries:
            path = safe_resolve(directory, entry.file)
            if not path.exists():
                continue

            # Check all accounts uploaded
            all_uploaded = all(entry.account_ids.get(name, "—") != "—" for name in account_names)
            if not all_uploaded:
                skipped += 1
                continue

            # Check transcript terminal
            if entry.transcript_status not in terminal:
                skipped += 1
                continue

            if dry_run:
                eligible.append(entry.file)
                continue

            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                errors.append(f"Failed to delete {entry.file}: {e}")

        return CleanReport(
            deleted=deleted,
            skipped=skipped,
            errors=errors,
            eligible=eligible,
        )
