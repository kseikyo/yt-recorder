from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_recorder.adapters.splitter import (
    TIER_1HR,
    TIER_15MIN,
    VideoSplitter,
    _compute_ffmpeg_timeout,
)
from yt_recorder.domain.exceptions import SplitterError

FFPROBE_JSON_RESPONSE = json.dumps({
    "streams": [
        {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
        }
    ],
    "format": {
        "duration": "3600.5",
        "size": "1073741824",
    },
})

FFPROBE_JSON_SHORT = json.dumps({
    "streams": [
        {
            "codec_name": "h264",
            "width": 1280,
            "height": 720,
        }
    ],
    "format": {
        "duration": "300.0",
        "size": "104857600",
    },
})


@pytest.fixture
def splitter() -> VideoSplitter:
    return VideoSplitter()


@pytest.fixture
def fake_video(tmp_path: Path) -> Path:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 1024)
    return video


class TestTierConstants:
    def test_tier_1hr_value(self) -> None:
        assert TIER_1HR == 3300.0

    def test_tier_15min_value(self) -> None:
        assert TIER_15MIN == 840.0


class TestGetDuration:
    def test_duration_from_json_ffprobe(self, splitter: VideoSplitter, fake_video: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = FFPROBE_JSON_RESPONSE

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            duration = splitter.get_duration(fake_video)

        assert duration == 3600.5
        call_args = mock_run.call_args[0][0]
        assert "-of" in call_args
        assert "json" in call_args
        assert "-show_format" in call_args
        assert "-show_streams" in call_args
        assert "-select_streams" in call_args

    def test_duration_ffprobe_not_found(self, splitter: VideoSplitter, fake_video: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(SplitterError, match="ffprobe not found"):
                splitter.get_duration(fake_video)

    def test_duration_ffprobe_nonzero_exit(self, splitter: VideoSplitter, fake_video: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "No such file"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SplitterError, match="ffprobe failed"):
                splitter.get_duration(fake_video)

    def test_duration_invalid_json(self, splitter: VideoSplitter, fake_video: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-json"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SplitterError, match="Cannot parse duration"):
                splitter.get_duration(fake_video)

    def test_duration_timeout_passed(self, splitter: VideoSplitter, fake_video: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = FFPROBE_JSON_RESPONSE

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            splitter.get_duration(fake_video)

        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 120


class TestNeedsSplit:
    def test_needs_split_true_when_over_threshold(self, splitter: VideoSplitter, fake_video: Path) -> None:
        with patch.object(splitter, "get_duration", return_value=4000.0):
            assert splitter.needs_split(fake_video, TIER_1HR) is True

    def test_needs_split_false_when_under_threshold(self, splitter: VideoSplitter, fake_video: Path) -> None:
        with patch.object(splitter, "get_duration", return_value=100.0):
            assert splitter.needs_split(fake_video, TIER_1HR) is False

    def test_needs_split_false_at_exact_threshold(self, splitter: VideoSplitter, fake_video: Path) -> None:
        with patch.object(splitter, "get_duration", return_value=TIER_1HR):
            assert splitter.needs_split(fake_video, TIER_1HR) is False


class TestSplit:
    def test_split_returns_original_when_no_split_needed(
        self, splitter: VideoSplitter, fake_video: Path
    ) -> None:
        with patch.object(splitter, "get_duration", return_value=100.0):
            result = splitter.split(fake_video, TIER_1HR)

        assert result == [fake_video]

    def test_split_returns_parts_when_split_needed(
        self, splitter: VideoSplitter, tmp_path: Path
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 1024)

        parts_dir = tmp_path / ".video_parts"
        parts_dir.mkdir()
        part0 = parts_dir / "video_part000.mp4"
        part1 = parts_dir / "video_part001.mp4"
        part0.write_bytes(b"\x00" * 512)
        part1.write_bytes(b"\x00" * 512)

        mock_result = MagicMock()
        mock_result.returncode = 0

        # get_duration: first call = source (oversize), then each part (under budget)
        durations = iter([4000.0, 2000.0, 2000.0])
        with patch.object(splitter, "get_duration", side_effect=lambda _p: next(durations)):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = splitter.split(video, TIER_1HR)

        assert len(result) == 2
        assert result == sorted(result)

        argv = mock_run.call_args[0][0]
        assert "-c:v" in argv
        assert "libx264" in argv
        assert "-preset" in argv
        assert "veryfast" in argv
        assert "-crf" in argv
        assert "23" in argv
        assert "-force_key_frames" in argv
        assert any(
            isinstance(a, str) and a.startswith("expr:gte(t,n_forced*") for a in argv
        )
        assert "-c:a" in argv
        assert "copy" in argv
        # stream-copy-all flag must NOT be present (would reintroduce the keyframe bug)
        pairs = list(zip(argv, argv[1:]))
        assert ("-c", "copy") not in pairs

    def test_split_raises_when_ffmpeg_not_found(
        self, splitter: VideoSplitter, fake_video: Path
    ) -> None:
        with patch.object(splitter, "get_duration", return_value=4000.0):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                with pytest.raises(SplitterError, match="ffmpeg not found"):
                    splitter.split(fake_video, TIER_1HR)

    def test_split_ffmpeg_timeout_scales_with_duration(
        self, splitter: VideoSplitter, tmp_path: Path
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 1024)

        parts_dir = tmp_path / ".video_parts"
        parts_dir.mkdir()
        part0 = parts_dir / "video_part000.mp4"
        part0.write_bytes(b"\x00" * 512)

        mock_result = MagicMock()
        mock_result.returncode = 0

        durations = iter([4000.0, 800.0])
        with patch.object(splitter, "get_duration", side_effect=lambda _p: next(durations)):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                splitter.split(video, TIER_1HR)

        _, kwargs = mock_run.call_args
        timeout = kwargs.get("timeout")
        assert timeout is not None
        assert timeout >= 600
        assert timeout == _compute_ffmpeg_timeout(4000.0)

    def test_split_raises_when_part_exceeds_threshold(
        self, splitter: VideoSplitter, tmp_path: Path
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 1024)

        parts_dir = tmp_path / ".video_parts"
        parts_dir.mkdir()
        part0 = parts_dir / "video_part000.mp4"
        part1 = parts_dir / "video_part001.mp4"
        part0.write_bytes(b"\x00" * 512)
        part1.write_bytes(b"\x00" * 512)

        mock_result = MagicMock()
        mock_result.returncode = 0

        # Source duration oversize, first part under budget, second part oversize
        durations = iter([4000.0, 800.0, 1200.0])
        with patch.object(splitter, "get_duration", side_effect=lambda _p: next(durations)):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(SplitterError, match="oversize part"):
                    splitter.split(video, TIER_15MIN)

        # cleanup should have removed the temp parts dir
        assert not part0.exists()
        assert not part1.exists()


class TestGetMetadata:
    def test_get_metadata_returns_correct_fields(
        self, splitter: VideoSplitter, fake_video: Path
    ) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = FFPROBE_JSON_RESPONSE

        with patch("subprocess.run", return_value=mock_result):
            meta = splitter.get_metadata(fake_video)

        assert meta["duration"] == 3600.5
        assert meta["size_bytes"] == 1073741824
        assert meta["codec"] == "h264"
        assert meta["width"] == 1920
        assert meta["height"] == 1080

    def test_get_metadata_no_streams(self, splitter: VideoSplitter, fake_video: Path) -> None:
        response = json.dumps({
            "streams": [],
            "format": {
                "duration": "100.0",
                "size": "1024",
            },
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = response

        with patch("subprocess.run", return_value=mock_result):
            meta = splitter.get_metadata(fake_video)

        assert meta["duration"] == 100.0
        assert meta["size_bytes"] == 1024
        assert meta["codec"] == ""
        assert meta["width"] == 0
        assert meta["height"] == 0

    def test_get_metadata_ffprobe_not_found(
        self, splitter: VideoSplitter, fake_video: Path
    ) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(SplitterError, match="ffprobe not found"):
                splitter.get_metadata(fake_video)

    def test_get_metadata_ffprobe_nonzero_exit(
        self, splitter: VideoSplitter, fake_video: Path
    ) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SplitterError, match="ffprobe failed"):
                splitter.get_metadata(fake_video)
