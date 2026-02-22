from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from yt_recorder.cli import main
from yt_recorder.config import Config
from yt_recorder.domain.models import (
    CleanReport,
    RegistryEntry,
    SyncReport,
    TranscriptStatus,
    YouTubeAccount,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestUploadCommand:
    def test_success(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(
                uploaded=3, upload_failed=0, deleted_count=2, kept_count=1
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["upload", str(tmp_path)])

            assert result.exit_code == 0
            assert "Uploaded: 3" in result.output
            assert "Failed: 0" in result.output
            assert "Deleted: 2" in result.output
            assert "Kept: 1" in result.output

    def test_dry_run(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(skipped=5)
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["upload", str(tmp_path), "--dry-run"])

            assert result.exit_code == 0
            assert "Would upload 5 files" in result.output

    def test_with_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(
                uploaded=1, upload_failed=1, errors=["Failed: timeout"]
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["upload", str(tmp_path)])

            assert "Errors:" in result.output
            assert "timeout" in result.output

    def test_passes_all_options(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport()
            mock_from.return_value = mock_pipeline

            result = runner.invoke(
                main,
                [
                    "upload",
                    str(tmp_path),
                    "--limit",
                    "5",
                    "--account",
                    "backup",
                    "--keep",
                    "--retry-failed",
                ],
            )

            assert result.exit_code == 0
            mock_pipeline.upload_new.assert_called_once_with(
                directory=tmp_path,
                limit=5,
                dry_run=False,
                keep=True,
                retry_failed=True,
                single_account="backup",
            )


class TestTranscribeCommand:
    def test_success(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.fetch_transcripts.return_value = SyncReport(
                transcripts_fetched=3, transcripts_pending=2
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["transcribe", str(tmp_path)])

            assert result.exit_code == 0
            assert "Transcripts fetched: 3" in result.output
            assert "Pending (not ready): 2" in result.output
            mock_from.assert_called_once_with(tmp_path, with_transcriber=True)

    def test_with_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.fetch_transcripts.return_value = SyncReport(
                errors=["No transcript for video.mp4"]
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["transcribe", str(tmp_path)])

            assert "Errors:" in result.output

    def test_passes_retry_force(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.fetch_transcripts.return_value = SyncReport()
            mock_from.return_value = mock_pipeline

            runner.invoke(main, ["transcribe", str(tmp_path), "--retry", "--force"])

            mock_pipeline.fetch_transcripts.assert_called_once_with(
                tmp_path, retry=True, force=True
            )


class TestSyncCommand:
    def test_success(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(uploaded=2)
            mock_pipeline.fetch_transcripts.return_value = SyncReport(
                transcripts_fetched=1, transcripts_pending=1
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["sync", str(tmp_path)])

            assert result.exit_code == 0
            assert "Uploaded: 2" in result.output
            assert "Fetched: 1" in result.output

    def test_dry_run_skips_transcripts(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(skipped=3)
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["sync", str(tmp_path), "--dry-run"])

            assert "Would upload 3 files" in result.output
            mock_pipeline.fetch_transcripts.assert_not_called()

    def test_shows_caption_note_on_upload(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.upload_new.return_value = SyncReport(uploaded=1)
            mock_pipeline.fetch_transcripts.return_value = SyncReport()
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["sync", str(tmp_path)])

            assert "auto-captions" in result.output


class TestCleanCommand:
    def test_success(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.clean_synced.return_value = CleanReport(deleted=3, skipped=1)
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["clean", str(tmp_path)])

            assert result.exit_code == 0
            assert "Deleted: 3" in result.output
            assert "Skipped: 1" in result.output

    def test_dry_run(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.clean_synced.return_value = CleanReport(
                eligible=["video1.mp4", "video2.mp4"]
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["clean", str(tmp_path), "--dry-run"])

            assert "Would delete 2 files" in result.output
            assert "video1.mp4" in result.output

    def test_dry_run_empty(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.clean_synced.return_value = CleanReport()
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["clean", str(tmp_path), "--dry-run"])

            assert "No files eligible" in result.output

    def test_with_errors(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("yt_recorder.pipeline.RecordingPipeline.from_directory") as mock_from:
            mock_pipeline = Mock()
            mock_pipeline.clean_synced.return_value = CleanReport(
                errors=["Failed to delete video.mp4: Permission denied"]
            )
            mock_from.return_value = mock_pipeline

            result = runner.invoke(main, ["clean", str(tmp_path)])

            assert "Errors" in result.output
            assert "Permission denied" in result.output


class TestStatusCommand:
    @patch("yt_recorder.adapters.scanner.scan_recordings")
    @patch("yt_recorder.adapters.registry.MarkdownRegistryStore")
    @patch("yt_recorder.config.load_config")
    def test_shows_file_status(
        self,
        mock_load_config: Mock,
        mock_registry_cls: Mock,
        mock_scan: Mock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        mock_load_config.return_value = Config(
            accounts=[
                YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
            ],
        )

        mock_registry = mock_registry_cls.return_value
        mock_registry.load.return_value = [
            RegistryEntry(
                "video1.mp4",
                "root",
                date.today(),
                TranscriptStatus.DONE,
                {"primary": "abc123"},
            ),
        ]

        mock_scan.return_value = [
            (tmp_path / "video1.mp4", "root"),
            (tmp_path / "video2.mp4", "root"),
        ]

        result = runner.invoke(main, ["status", str(tmp_path)])

        assert result.exit_code == 0
        assert "video1.mp4" in result.output
        assert "video2.mp4" in result.output
        assert "not uploaded" in result.output

    @patch("yt_recorder.adapters.scanner.scan_recordings")
    @patch("yt_recorder.adapters.registry.MarkdownRegistryStore")
    @patch("yt_recorder.config.load_config")
    def test_handles_missing_registry(
        self,
        mock_load_config: Mock,
        mock_registry_cls: Mock,
        mock_scan: Mock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        mock_load_config.return_value = Config(accounts=[])

        mock_registry_cls.return_value.load.side_effect = FileNotFoundError

        mock_scan.return_value = [(tmp_path / "video.mp4", "root")]

        result = runner.invoke(main, ["status", str(tmp_path)])

        assert result.exit_code == 0
        assert "not uploaded" in result.output
