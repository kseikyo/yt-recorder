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
