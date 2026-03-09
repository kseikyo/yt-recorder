from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Callable, cast

from yt_recorder.adapters.raid import RaidAdapter
from yt_recorder.adapters.registry import MarkdownRegistryStore
from yt_recorder.adapters.scanner import scan_recordings
from yt_recorder.adapters.transcriber import YtdlpTranscriptAdapter
from yt_recorder.config import Config, load_config, save_detected_limit
from yt_recorder.domain.exceptions import (
    ChannelCreationRequiredError,
    DailyLimitError,
    RegistryFileNotFoundError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
    VideoTooLongError,
)
from yt_recorder.domain.formatters import format_transcript_md, parse_srt, title_from_filename
from yt_recorder.domain.models import (
    CleanReport,
    PlaylistReport,
    RegistryEntry,
    SyncReport,
    TranscriptStatus,
    UploadResult,
)
from yt_recorder.domain.protocols import RegistryStore, TranscriptFetcher
from yt_recorder.utils import safe_resolve

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from yt_recorder.adapters.splitter import VideoSplitter
    from yt_recorder.domain.models import YouTubeAccount


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
        playlist_failed = 0
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

        from yt_recorder.adapters.splitter import VideoSplitter

        splitter = VideoSplitter()
        self.raid.open()
        stop_all_uploads = False

        try:
            for idx, (path, playlist) in enumerate(files_to_process):
                if stop_all_uploads:
                    break
                if progress_callback:
                    progress_callback(idx + 1, len(files_to_process), path.name)
                try:
                    title = title_from_filename(path.name)
                    file_key = str(path.relative_to(directory))

                    if single_account:
                        adapter = self.raid.get_adapter(single_account)
                        result = adapter.upload(path, title)
                        results: dict[str, UploadResult | None] = {single_account: result}
                        pl_ok = adapter.assign_playlist(result.video_id, playlist)
                        if not pl_ok:
                            playlist_failed += 1
                    else:
                        if not isinstance(getattr(self.raid, "mirrors", None), list):
                            results, pf = self.raid.upload(path, title, playlist)
                            playlist_failed += pf
                        else:
                            duration: float | None = None
                            accounts = [self.raid.primary, *self.raid.mirrors]
                            all_account_results: dict[str, UploadResult | None] = {
                                account.name: None for account in accounts
                            }

                            for account in accounts:
                                account_name = account.name
                                try:
                                    account_limit = account.upload_limit_secs
                                    if account_limit is not None:
                                        if duration is None:
                                            duration = splitter.get_duration(path)
                                        over_limit = duration > account_limit
                                    else:
                                        over_limit = False

                                    if over_limit:
                                        if account_limit is None:
                                            continue
                                        assert account_limit is not None
                                        temp_dir = path.parent / f".{path.stem}_parts"
                                        if temp_dir.exists():
                                            parts = sorted(
                                                temp_dir.glob(f"{path.stem}_part*{path.suffix}")
                                            )
                                            if not parts:
                                                parts = splitter.split(path, account_limit)
                                        else:
                                            parts = splitter.split(path, account_limit)
                                        self._upload_parts_to_account(
                                            raid=self.raid,
                                            registry=self.registry,
                                            account_name=account_name,
                                            parts=parts,
                                            base_title=title,
                                            playlist=playlist,
                                            original_path=path,
                                            directory=directory,
                                        )
                                    else:
                                        result = self.raid.upload_to_account(
                                            account_name, path, title
                                        )
                                        playlist_ok = self.raid.assign_playlist_to_account(
                                            account_name,
                                            result.video_id,
                                            playlist,
                                        )
                                        if not playlist_ok:
                                            playlist_failed += 1
                                        all_account_results[account_name] = result
                                except VideoTooLongError:
                                    detected_limit = self._detect_tier(
                                        raid=self.raid,
                                        splitter=splitter,
                                        account=account,
                                        path=path,
                                        title=title,
                                        playlist=playlist,
                                        directory=directory,
                                        registry=self.registry,
                                    )
                                    if detected_limit is not None:
                                        config_path = Config.default_config_dir() / "config.toml"
                                        save_detected_limit(
                                            config_path, account_name, detected_limit
                                        )
                                except DailyLimitError:
                                    logger.warning("Daily limit hit for %s, stopping", account_name)
                                    stop_all_uploads = True
                                    break

                            results = all_account_results

                    all_succeeded = all(r is not None for r in results.values())

                    entry = RegistryEntry(
                        file=file_key,
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

                except ChannelCreationRequiredError as e:
                    errors.append(f"Failed to upload {path}: {e}")
                    upload_failed += 1
                    stop_all_uploads = True
                    logger.exception("Upload blocked by channel creation gate for %s", path)
                    break
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
                    file_path = safe_resolve(directory, entry.file)
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
            playlist_failed=playlist_failed,
            total_registered=len(entries) + uploaded,
            errors=errors,
        )

    def _detect_tier(
        self,
        raid: RaidAdapter,
        splitter: VideoSplitter,
        account: YouTubeAccount,
        path: Path,
        title: str,
        playlist: str,
        directory: Path,
        registry: RegistryStore,
    ) -> float | None:
        from yt_recorder.adapters.splitter import TIER_1HR, TIER_15MIN

        account_name = account.name
        # Clean up any stale temp dir from a previous crashed tier detection attempt
        _temp_dir = path.parent / f".{path.stem}_parts"
        if _temp_dir.exists():
            _existing = list(_temp_dir.iterdir())
            splitter.cleanup_parts(_existing)
        for tier_limit in [TIER_1HR, TIER_15MIN]:
            parts = splitter.split(path, tier_limit)
            try:
                self._upload_parts_to_account(
                    raid=raid,
                    registry=registry,
                    account_name=account_name,
                    parts=parts,
                    base_title=title,
                    playlist=playlist,
                    original_path=path,
                    directory=directory,
                )
                return tier_limit
            except VideoTooLongError:
                splitter.cleanup_parts(parts)
                continue
        logger.error("All tiers failed for %s on account %s", path.name, account_name)
        return None

    def _upload_parts_to_account(
        self,
        raid: RaidAdapter,
        registry: RegistryStore,
        account_name: str,
        parts: list[Path],
        base_title: str,
        playlist: str,
        original_path: Path,
        directory: Path,
    ) -> None:
        n = len(parts)
        if n == 0:
            return

        file_key = str(original_path.relative_to(directory))
        truncated_base = base_title[:100]

        registry_with_parts = cast(MarkdownRegistryStore, registry)
        existing_parts = registry_with_parts.get_parts_for_parent(file_key)
        uploaded_part_indexes = {
            e.part_index
            for e in existing_parts
            if e.part_index is not None and e.account_ids.get(account_name, "—") != "—"
        }

        for i, part in enumerate(parts, 1):
            if i in uploaded_part_indexes:
                continue

            part_title = f"{truncated_base} [Part {i}/{n}]"
            description = f"Part {i} of {n}. Original: {original_path.name}"
            result = raid.upload_to_account(account_name, part, part_title, description=description)
            playlist_ok = raid.assign_playlist_to_account(account_name, result.video_id, playlist)
            if not playlist_ok:
                logger.warning(
                    "Playlist assignment failed for %s on %s",
                    playlist,
                    account_name,
                )

            part_file_key = str(part.relative_to(directory))
            entry = RegistryEntry(
                file=part_file_key,
                playlist=playlist,
                uploaded_date=date.today(),
                transcript_status=TranscriptStatus.PENDING,
                account_ids={account_name: result.video_id},
                part_index=i,
                total_parts=n,
                parent_file=file_key,
            )
            registry.append(entry)

    def assign_playlists(
        self,
        directory: Path,
        single_account: str | None = None,
        dry_run: bool = False,
        on_progress: Callable[[str, str, str, bool], None] | None = None,
    ) -> PlaylistReport:
        """Assign playlists to uploaded videos.

        Args:
            directory: Recordings directory
            single_account: Filter to single account only
            dry_run: Show plan without executing
            on_progress: Callback(account, video_id, playlist, success)

        Returns:
            PlaylistReport with assignment counts and errors
        """
        assigned = 0
        failed = 0
        skipped = 0
        errors: list[str] = []

        try:
            entries = self.registry.load()
        except RegistryFileNotFoundError:
            entries = []

        if dry_run:
            for entry in entries:
                if not entry.playlist or not entry.account_ids:
                    skipped += 1
                    continue
                for account_name, video_id in entry.account_ids.items():
                    if video_id == "—":
                        skipped += 1
                        continue
                    if single_account and account_name != single_account:
                        continue
                    if on_progress:
                        on_progress(account_name, video_id, entry.playlist, False)
            return PlaylistReport(assigned=0, failed=0, skipped=skipped, errors=errors)

        self.raid.open()

        try:
            for entry in entries:
                if not entry.playlist or not entry.account_ids:
                    skipped += 1
                    continue

                for account_name, video_id in entry.account_ids.items():
                    if video_id == "—":
                        skipped += 1
                        continue

                    if single_account and account_name != single_account:
                        continue

                    try:
                        adapter = self.raid.get_adapter(account_name)
                        success = adapter.assign_playlist(video_id, entry.playlist)

                        if success:
                            assigned += 1
                        else:
                            failed += 1
                            errors.append(
                                f"Failed to assign {entry.playlist} to {video_id} on {account_name}"
                            )

                        if on_progress:
                            on_progress(account_name, video_id, entry.playlist, success)

                    except Exception as e:
                        failed += 1
                        errors.append(
                            f"Error assigning {entry.playlist} to {video_id} on {account_name}: {e}"
                        )
                        logger.exception(
                            "Playlist assignment failed for %s on %s", video_id, account_name
                        )

        finally:
            self.raid.close()

        return PlaylistReport(
            assigned=assigned,
            failed=failed,
            skipped=skipped,
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
                safe_entry = safe_resolve(directory, entry.file)
                rel_entry = safe_entry.relative_to(directory.resolve())
                transcript_path = directory / "transcripts" / rel_entry.with_suffix(".md")
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

        from yt_recorder.adapters.splitter import VideoSplitter

        splitter = VideoSplitter()
        registry_with_coverage = cast(MarkdownRegistryStore, self.registry)

        for entry in entries:
            path = safe_resolve(directory, entry.file)
            if not path.exists():
                continue

            all_covered: bool
            coverage_results: list[bool] = []
            coverage_supported = True
            for name in account_names:
                covered = registry_with_coverage.is_account_covered(entry.file, name)
                if not isinstance(covered, bool):
                    coverage_supported = False
                    break
                coverage_results.append(covered)

            if coverage_supported:
                all_covered = all(coverage_results)
            else:
                all_covered = all(entry.account_ids.get(name, "—") != "—" for name in account_names)

            if not all_covered:
                skipped += 1
                continue

            # Check transcript terminal — skip for split parents (no video_id to fetch transcript from)
            parts_for_entry = registry_with_coverage.get_parts_for_parent(entry.file)
            is_split_parent = bool(parts_for_entry)

            if not is_split_parent and entry.transcript_status not in terminal:
                skipped += 1
                continue

            if dry_run:
                eligible.append(entry.file)
                continue

            try:
                path.unlink()
                temp_dir = path.parent / f".{path.stem}_parts"
                if temp_dir.exists():
                    parts = sorted(temp_dir.glob(f"{path.stem}_part*{path.suffix}"))
                    if parts:
                        splitter.cleanup_parts(parts)
                deleted += 1
            except OSError as e:
                errors.append(f"Failed to delete {entry.file}: {e}")

        return CleanReport(
            deleted=deleted,
            skipped=skipped,
            errors=errors,
            eligible=eligible,
        )
