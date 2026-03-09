from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from yt_recorder.adapters.splitter import TIER_15MIN
from yt_recorder.config import Config
from yt_recorder.domain.exceptions import PhoneVerificationRequiredError
from yt_recorder.domain.models import UploadResult, YouTubeAccount
from yt_recorder.pipeline import RecordingPipeline


def _config(accounts: list[YouTubeAccount]) -> Config:
    return Config(
        accounts=accounts,
        extensions=(".mp4",),
        exclude_dirs=frozenset(),
        max_depth=1,
    )


def test_upload_new_splits_on_phone_verification_per_account(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    accounts = [
        YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
        YouTubeAccount("backup", Path("/tmp/b.json"), Path("/tmp/b.txt"), "mirror"),
    ]

    registry = Mock()
    registry.load.return_value = []
    raid = Mock()
    raid.primary = accounts[0]
    raid.mirrors = [accounts[1]]
    raid.assign_playlist_to_account.return_value = True

    def upload_side_effect(account_name: str, *_args: object, **_kwargs: object) -> UploadResult:
        if account_name == "primary":
            raise PhoneVerificationRequiredError()
        return UploadResult("b1", "https://youtu.be/b1", "title", "backup")

    raid.upload_to_account.side_effect = upload_side_effect

    pipeline = RecordingPipeline(_config(accounts), registry, raid)

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "root")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter_cls.return_value.split.return_value = [tmp_path / "part1.mp4"]
            with patch.object(pipeline, "_upload_parts_to_account") as upload_parts:
                with patch("yt_recorder.pipeline.save_detected_limit") as save_limit:
                    report = pipeline.upload_new(tmp_path)

    assert report.uploaded == 1
    assert upload_parts.call_count == 1
    assert upload_parts.call_args.kwargs["account_name"] == "primary"
    save_limit.assert_called_once_with(
        Config.default_config_dir() / "config.toml",
        "primary",
        TIER_15MIN,
    )


def test_upload_new_single_account_splits_on_phone_verification(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    account = YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary")

    registry = Mock()
    registry.load.return_value = []
    raid = Mock()
    blocked_adapter = Mock()
    blocked_adapter.upload.side_effect = PhoneVerificationRequiredError()
    raid.get_adapter.return_value = blocked_adapter

    pipeline = RecordingPipeline(_config([account]), registry, raid)

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "root")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter_cls.return_value.split.return_value = [tmp_path / "part1.mp4"]
            with patch.object(pipeline, "_upload_parts_to_account") as upload_parts:
                with patch("yt_recorder.pipeline.save_detected_limit") as save_limit:
                    report = pipeline.upload_new(tmp_path, single_account="primary")

    assert report.uploaded == 1
    assert upload_parts.call_count == 1
    assert upload_parts.call_args.kwargs["account_name"] == "primary"
    save_limit.assert_called_once_with(
        Config.default_config_dir() / "config.toml",
        "primary",
        TIER_15MIN,
    )
    appended_entry = registry.append.call_args.args[0]
    assert appended_entry.account_ids == {"primary": "—"}
