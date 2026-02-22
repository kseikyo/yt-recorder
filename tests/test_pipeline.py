from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

from yt_recorder.config import Config
from yt_recorder.domain.exceptions import (
    RegistryFileNotFoundError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
)
from yt_recorder.domain.models import RegistryEntry, TranscriptStatus, UploadResult, YouTubeAccount
from yt_recorder.pipeline import RecordingPipeline


class TestRecordingPipeline:
    """Test suite for RecordingPipeline."""

    @pytest.fixture
    def config(self) -> Config:
        return Config(
            accounts=[
                YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
                YouTubeAccount("mirror", Path("/tmp/m.json"), Path("/tmp/m.txt"), "mirror"),
            ],
            extensions=(".mp4",),
            exclude_dirs=frozenset(),
            max_depth=1,
        )

    @pytest.fixture
    def mock_registry(self) -> Mock:
        registry = Mock()
        registry.load = Mock(return_value=[])
        registry.append = Mock()
        return registry

    @pytest.fixture
    def mock_raid(self) -> Mock:
        raid = Mock()
        raid.open = Mock()
        raid.close = Mock()
        raid.upload = Mock(
            return_value={
                "primary": UploadResult("abc123", "https://youtu.be/abc123", "Test", "primary"),
                "mirror": UploadResult("def456", "https://youtu.be/def456", "Test", "mirror"),
            }
        )
        raid._adapters = {
            "primary": Mock(),
            "mirror": Mock(),
        }
        return raid

    def test_upload_new_dry_run(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test dry-run mode doesn't upload."""
        # Create test file
        (tmp_path / "test.mp4").write_text("fake video")

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path, dry_run=True)

        assert report.skipped == 1
        mock_raid.open.assert_not_called()

    def test_upload_new_uploads_file(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test successful upload."""
        (tmp_path / "test.mp4").write_text("fake video")

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path)

        assert report.uploaded == 1
        assert report.deleted_count == 1  # File deleted after successful upload
        mock_registry.append.assert_called_once()

    def test_upload_new_with_limit(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test limit parameter."""
        (tmp_path / "test1.mp4").write_text("fake")
        (tmp_path / "test2.mp4").write_text("fake")

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path, limit=1)

        assert report.uploaded == 1
        assert mock_raid.upload.call_count == 1

    def test_upload_new_keeps_file_on_failure(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test file is kept if any mirror fails."""
        (tmp_path / "test.mp4").write_text("fake video")
        mock_raid.upload = Mock(
            return_value={
                "primary": UploadResult("abc123", "https://youtu.be/abc123", "Test", "primary"),
                "mirror": None,  # Mirror failed
            }
        )

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path)

        assert report.uploaded == 1
        assert report.kept_count == 1  # Kept because mirror failed
        assert report.deleted_count == 0

    def test_upload_new_with_keep_flag(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test --keep flag preserves files."""
        (tmp_path / "test.mp4").write_text("fake video")

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path, keep=True)

        assert report.uploaded == 1
        assert report.kept_count == 1
        assert report.deleted_count == 0

    def test_upload_new_skips_registered(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """Test already-registered files are skipped."""
        (tmp_path / "test.mp4").write_text("fake video")
        mock_registry.load = Mock(
            return_value=[RegistryEntry("test.mp4", "", date.today(), TranscriptStatus.PENDING, {})]
        )

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path)

        assert report.uploaded == 0
        mock_raid.upload.assert_not_called()

    def test_upload_no_files_skips_browser_launch(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """H5: No browsers opened when 0 files to process."""
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path)

        assert report.uploaded == 0
        mock_raid.open.assert_not_called()

    def test_retry_failed_re_uploads_dashed_accounts(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """C2: --retry-failed re-uploads to accounts with '—'."""
        (tmp_path / "test.mp4").write_text("fake video")
        mirror_adapter = mock_raid._adapters["mirror"]
        mirror_adapter.upload.return_value = UploadResult(
            "new456",
            "https://youtu.be/new456",
            "Test",
            "mirror",
        )

        mock_registry.load = Mock(
            return_value=[
                RegistryEntry(
                    "test.mp4",
                    "root",
                    date.today(),
                    TranscriptStatus.PENDING,
                    {"primary": "abc123", "mirror": "—"},
                )
            ]
        )

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path, retry_failed=True)

        assert report.uploaded == 1
        mirror_adapter.upload.assert_called_once()
        mirror_adapter.assign_playlist.assert_called_once_with("new456", "root")
        mock_registry.update_account_id.assert_called_once_with(
            "test.mp4",
            "mirror",
            "new456",
        )

    def test_retry_failed_missing_file(
        self, config: Config, mock_registry: Mock, mock_raid: Mock, tmp_path: Path
    ) -> None:
        """C2: retry reports error when local file is deleted."""
        mock_registry.load = Mock(
            return_value=[
                RegistryEntry(
                    "gone.mp4",
                    "root",
                    date.today(),
                    TranscriptStatus.PENDING,
                    {"primary": "abc123", "mirror": "—"},
                )
            ]
        )

        pipeline = RecordingPipeline(config, mock_registry, mock_raid)
        report = pipeline.upload_new(tmp_path, retry_failed=True)

        assert report.uploaded == 0
        assert any("file not found" in e for e in report.errors)


class TestFetchTranscripts:
    @pytest.fixture
    def config(self) -> Config:
        return Config(
            accounts=[
                YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
                YouTubeAccount("mirror", Path("/tmp/m.json"), Path("/tmp/m.txt"), "mirror"),
            ],
            extensions=(".mp4",),
            exclude_dirs=frozenset(),
            max_depth=1,
            transcript_delay=0.0,
        )

    @pytest.fixture
    def mock_registry(self) -> Mock:
        registry = Mock()
        registry.load = Mock(return_value=[])
        registry.update_many = Mock()
        return registry

    @pytest.fixture
    def mock_raid(self) -> Mock:
        return Mock()

    @pytest.fixture
    def mock_transcriber(self, tmp_path: Path) -> Mock:
        transcriber = Mock()
        srt_path = tmp_path / ".tmp" / "test.srt"
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello world\n\n")
        transcriber.fetch = Mock(return_value=srt_path)
        return transcriber

    def _entry(
        self,
        file: str = "video.mp4",
        status: TranscriptStatus = TranscriptStatus.PENDING,
        video_id: str = "abc123",
    ) -> RegistryEntry:
        return RegistryEntry(
            file=file,
            playlist="root",
            uploaded_date=date.today(),
            transcript_status=status,
            account_ids={"primary": video_id, "mirror": "def456"},
        )

    def test_success_updates_to_done(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        mock_transcriber: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [self._entry()]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, mock_transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert report.transcripts_fetched == 1
        mock_registry.update_many.assert_called_once()
        updates = mock_registry.update_many.call_args[0][0]
        assert updates["video.mp4"]["transcript_status"] == TranscriptStatus.DONE

    def test_unavailable_updates_to_unavailable(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [self._entry()]
        transcriber = Mock()
        transcriber.fetch.side_effect = TranscriptUnavailableError("No captions")
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert report.transcripts_fetched == 0
        updates = mock_registry.update_many.call_args[0][0]
        assert updates["video.mp4"]["transcript_status"] == TranscriptStatus.UNAVAILABLE

    def test_not_ready_stays_pending(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [self._entry()]
        transcriber = Mock()
        transcriber.fetch.side_effect = TranscriptNotReadyError("Processing")
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert report.transcripts_pending == 1
        mock_registry.update_many.assert_not_called()

    def test_generic_exception_updates_to_error(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [self._entry()]
        transcriber = Mock()
        transcriber.fetch.side_effect = RuntimeError("Connection timeout")
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        updates = mock_registry.update_many.call_args[0][0]
        assert updates["video.mp4"]["transcript_status"] == TranscriptStatus.ERROR
        assert any("Connection timeout" in e for e in report.errors)

    def test_retry_flag_includes_error_state(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        mock_transcriber: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [
            self._entry(status=TranscriptStatus.ERROR),
        ]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, mock_transcriber)

        report_no_retry = pipeline.fetch_transcripts(tmp_path, retry=False)
        assert report_no_retry.transcripts_fetched == 0

        mock_registry.update_many.reset_mock()

        report_retry = pipeline.fetch_transcripts(tmp_path, retry=True)
        assert report_retry.transcripts_fetched == 1

    def test_force_flag_processes_all(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        mock_transcriber: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [
            self._entry(file="done.mp4", status=TranscriptStatus.DONE, video_id="d1"),
            self._entry(file="unavail.mp4", status=TranscriptStatus.UNAVAILABLE, video_id="u1"),
        ]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, mock_transcriber)

        report = pipeline.fetch_transcripts(tmp_path, force=True)

        assert report.transcripts_fetched == 2

    def test_no_primary_account(
        self,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        config = Config(
            accounts=[
                YouTubeAccount("mirror", Path("/tmp/m.json"), Path("/tmp/m.txt"), "mirror"),
            ],
        )
        transcriber = Mock()
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert "No primary account" in report.errors[0]

    def test_no_transcriber(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber=None)

        report = pipeline.fetch_transcripts(tmp_path)

        assert "Transcriber not initialized" in report.errors[0]

    def test_empty_registry(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = []
        transcriber = Mock()
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert report.transcripts_fetched == 0
        assert report.transcripts_pending == 0

    def test_batch_update_called_once(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        mock_transcriber: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [
            self._entry(file="v1.mp4", video_id="id1"),
            self._entry(file="v2.mp4", video_id="id2"),
            self._entry(file="v3.mp4", video_id="id3"),
        ]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid, mock_transcriber)

        report = pipeline.fetch_transcripts(tmp_path)

        assert report.transcripts_fetched == 3
        mock_registry.update_many.assert_called_once()
        updates = mock_registry.update_many.call_args[0][0]
        assert len(updates) == 3


class TestCleanSynced:
    @pytest.fixture
    def config(self) -> Config:
        return Config(
            accounts=[
                YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
                YouTubeAccount("mirror", Path("/tmp/m.json"), Path("/tmp/m.txt"), "mirror"),
            ],
        )

    @pytest.fixture
    def mock_registry(self) -> Mock:
        registry = Mock()
        registry.load = Mock(return_value=[])
        return registry

    @pytest.fixture
    def mock_raid(self) -> Mock:
        return Mock()

    def _entry(
        self,
        file: str = "video.mp4",
        status: TranscriptStatus = TranscriptStatus.DONE,
        accounts: dict[str, str] | None = None,
    ) -> RegistryEntry:
        if accounts is None:
            accounts = {"primary": "abc123", "mirror": "def456"}
        return RegistryEntry(
            file=file,
            playlist="root",
            uploaded_date=date.today(),
            transcript_status=status,
            account_ids=accounts,
        )

    def test_deletes_when_all_accounts_and_done(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry()]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 1
        assert not (tmp_path / "video.mp4").exists()

    def test_deletes_when_all_accounts_and_unavailable(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry(status=TranscriptStatus.UNAVAILABLE)]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 1

    def test_skips_pending(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry(status=TranscriptStatus.PENDING)]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0
        assert report.skipped == 1
        assert (tmp_path / "video.mp4").exists()

    def test_skips_error(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry(status=TranscriptStatus.ERROR)]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0
        assert report.skipped == 1

    def test_skips_missing_account(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [
            self._entry(accounts={"primary": "abc123", "mirror": "\u2014"})
        ]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0
        assert report.skipped == 1

    def test_skips_file_not_on_disk(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = [self._entry()]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0

    def test_dry_run_populates_eligible(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry()]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path, dry_run=True)

        assert report.eligible == ["video.mp4"]
        assert report.deleted == 0
        assert (tmp_path / "video.mp4").exists()

    def test_oserror_reported_in_errors(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "video.mp4").write_text("data")
        mock_registry.load.return_value = [self._entry()]
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            report = pipeline.clean_synced(tmp_path)

        assert len(report.errors) == 1
        assert "Permission denied" in report.errors[0]

    def test_empty_registry(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.return_value = []
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0
        assert report.skipped == 0

    def test_missing_registry(
        self,
        config: Config,
        mock_registry: Mock,
        mock_raid: Mock,
        tmp_path: Path,
    ) -> None:
        mock_registry.load.side_effect = RegistryFileNotFoundError
        pipeline = RecordingPipeline(config, mock_registry, mock_raid)

        report = pipeline.clean_synced(tmp_path)

        assert report.deleted == 0
