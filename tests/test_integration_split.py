from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

from yt_recorder.adapters.registry import MarkdownRegistryStore
from yt_recorder.adapters.splitter import TIER_1HR
from yt_recorder.config import Config, load_config, save_detected_limit
from yt_recorder.domain.exceptions import DailyLimitError, VideoTooLongError
from yt_recorder.domain.models import RegistryEntry, TranscriptStatus, UploadResult, YouTubeAccount
from yt_recorder.pipeline import RecordingPipeline

MISSING = "\u2014"


class InMemoryRegistry:
    def __init__(self, entries: list[RegistryEntry] | None = None) -> None:
        self.entries = list(entries or [])

    def load(self) -> list[RegistryEntry]:
        return list(self.entries)

    def append(self, entry: RegistryEntry) -> None:
        self.entries.append(entry)

    def get_parts_for_parent(self, parent_file: str) -> list[RegistryEntry]:
        return [entry for entry in self.entries if entry.parent_file == parent_file]

    def update_many(self, updates: dict[str, dict[str, object]]) -> None:
        for idx, entry in enumerate(self.entries):
            if entry.file in updates:
                fields = updates[entry.file]
                self.entries[idx] = RegistryEntry(
                    file=entry.file,
                    playlist=entry.playlist,
                    uploaded_date=entry.uploaded_date,
                    transcript_status=cast(
                        TranscriptStatus,
                        fields.get("transcript_status", entry.transcript_status),
                    ),
                    account_ids=cast(dict[str, str], fields.get("account_ids", entry.account_ids)),
                    part_index=entry.part_index,
                    total_parts=entry.total_parts,
                    parent_file=entry.parent_file,
                )

    def update_account_id(self, file: str, account: str, video_id: str) -> None:
        for idx, entry in enumerate(self.entries):
            if entry.file == file:
                account_ids = dict(entry.account_ids)
                account_ids[account] = video_id
                self.entries[idx] = RegistryEntry(
                    file=entry.file,
                    playlist=entry.playlist,
                    uploaded_date=entry.uploaded_date,
                    transcript_status=entry.transcript_status,
                    account_ids=account_ids,
                    part_index=entry.part_index,
                    total_parts=entry.total_parts,
                    parent_file=entry.parent_file,
                )
                return


def _config(accounts: list[YouTubeAccount]) -> Config:
    return Config(
        accounts=accounts,
        extensions=(".mp4",),
        exclude_dirs=frozenset(),
        max_depth=1,
    )


def _result(video_id: str, account_name: str, title: str = "Video") -> UploadResult:
    return UploadResult(video_id, f"https://youtu.be/{video_id}", title, account_name)


def test_primary_keeps_full_upload_while_backup_registers_split_parts(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")
    parts = [tmp_path / ".video_parts" / f"video_part00{i}.mp4" for i in range(1, 4)]

    accounts = [
        YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
        YouTubeAccount(
            "backup",
            Path("/tmp/b.json"),
            Path("/tmp/b.txt"),
            "mirror",
            upload_limit_secs=3300.0,
        ),
    ]
    registry = InMemoryRegistry()
    raid = Mock()
    raid.primary = accounts[0]
    raid.mirrors = [accounts[1]]
    raid.assign_playlist_to_account.return_value = True

    def upload_side_effect(
        account_name: str, upload_path: Path, title: str, description: str = ""
    ) -> UploadResult:
        if account_name == "primary":
            assert upload_path == path
            return _result("primary-full", account_name, title)
        return _result(f"backup-part-{parts.index(upload_path) + 1}", account_name, title)

    raid.upload_to_account.side_effect = upload_side_effect

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "recordings")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter = splitter_cls.return_value
            splitter.get_duration.return_value = 7200.0
            splitter.split.return_value = parts

            report = RecordingPipeline(_config(accounts), registry, raid).upload_new(
                tmp_path, keep=True
            )

    assert report.uploaded == 1
    original = next(entry for entry in registry.entries if entry.file == "video.mp4")
    assert original.account_ids == {"primary": "primary-full", "backup": MISSING}

    part_entries = sorted(
        (entry for entry in registry.entries if entry.parent_file == "video.mp4"),
        key=lambda entry: cast(int, entry.part_index),
    )
    assert len(part_entries) == 3
    assert [entry.part_index for entry in part_entries] == [1, 2, 3]
    assert [entry.total_parts for entry in part_entries] == [3, 3, 3]
    assert [entry.account_ids for entry in part_entries] == [
        {"backup": "backup-part-1"},
        {"backup": "backup-part-2"},
        {"backup": "backup-part-3"},
    ]


def test_unknown_limit_detects_tier_and_saves_it(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")
    parts = [tmp_path / ".video_parts" / f"video_part00{i}.mp4" for i in range(1, 3)]

    account = YouTubeAccount(
        "primary",
        Path("/tmp/p.json"),
        Path("/tmp/p.txt"),
        "primary",
        upload_limit_secs=None,
    )
    registry = InMemoryRegistry()
    raid = Mock()
    raid.primary = account
    raid.mirrors = []
    raid.assign_playlist_to_account.return_value = True

    def upload_side_effect(
        account_name: str, upload_path: Path, title: str, description: str = ""
    ) -> UploadResult:
        if upload_path == path:
            raise VideoTooLongError("too long")
        return _result(f"part-{parts.index(upload_path) + 1}", account_name, title)

    raid.upload_to_account.side_effect = upload_side_effect

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "recordings")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            with patch("yt_recorder.pipeline.save_detected_limit") as save_limit:
                splitter = splitter_cls.return_value
                splitter.split.return_value = parts

                report = RecordingPipeline(_config([account]), registry, raid).upload_new(
                    tmp_path,
                    keep=True,
                )

    assert report.uploaded == 1
    assert save_limit.call_count == 1
    assert save_limit.call_args.args[1] == "primary"
    assert save_limit.call_args.args[2] == TIER_1HR

    part_entries = sorted(
        (entry for entry in registry.entries if entry.parent_file == "video.mp4"),
        key=lambda entry: cast(int, entry.part_index),
    )
    assert [entry.account_ids for entry in part_entries] == [
        {"primary": "part-1"},
        {"primary": "part-2"},
    ]


def test_daily_limit_during_parts_stops_remaining_uploads(tmp_path: Path) -> None:
    first = tmp_path / "video.mp4"
    second = tmp_path / "later.mp4"
    first.write_text("x")
    second.write_text("x")
    parts = [tmp_path / ".video_parts" / f"video_part00{i}.mp4" for i in range(1, 5)]

    account = YouTubeAccount(
        "primary",
        Path("/tmp/p.json"),
        Path("/tmp/p.txt"),
        "primary",
        upload_limit_secs=3300.0,
    )
    registry = InMemoryRegistry()
    raid = Mock()
    raid.primary = account
    raid.mirrors = []
    raid.assign_playlist_to_account.return_value = True

    def upload_side_effect(
        account_name: str, upload_path: Path, title: str, description: str = ""
    ) -> UploadResult:
        if upload_path == parts[0]:
            return _result("part-1", account_name, title)
        if upload_path == parts[1]:
            return _result("part-2", account_name, title)
        if upload_path == parts[2]:
            raise DailyLimitError("limit")
        raise AssertionError(f"unexpected upload: {upload_path}")

    raid.upload_to_account.side_effect = upload_side_effect

    with patch(
        "yt_recorder.pipeline.scan_recordings",
        return_value=[(first, "recordings"), (second, "recordings")],
    ):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter = splitter_cls.return_value
            splitter.get_duration.return_value = 7200.0
            splitter.split.return_value = parts

            report = RecordingPipeline(_config([account]), registry, raid).upload_new(
                tmp_path, keep=True
            )

    assert report.uploaded == 1
    assert raid.upload_to_account.call_count == 3
    assert all(entry.file != "later.mp4" for entry in registry.entries)

    original = next(entry for entry in registry.entries if entry.file == "video.mp4")
    assert original.account_ids == {"primary": MISSING}

    part_entries = sorted(
        (entry for entry in registry.entries if entry.parent_file == "video.mp4"),
        key=lambda entry: cast(int, entry.part_index),
    )
    assert [entry.part_index for entry in part_entries] == [1, 2]
    assert [entry.account_ids for entry in part_entries] == [
        {"primary": "part-1"},
        {"primary": "part-2"},
    ]


def test_flat_config_round_trips_detected_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[accounts]\nprimary = "/tmp/some.json"\n', encoding="utf-8")

    initial = load_config(config_path)
    assert initial.accounts[0].upload_limit_secs is None

    save_detected_limit(config_path, "primary", 3300.0)

    reloaded = load_config(config_path)
    assert reloaded.accounts[0].upload_limit_secs == 3300.0


def test_v2_registry_upgrades_to_v3_with_part_fields(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.md"
    registry_path.write_text(
        "# Recordings Registry\n\n"
        "| File | Playlist | Uploaded | Transcript | primary |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| video.mp4 | recordings | 2024-01-01 | pending | abc123 |\n",
        encoding="utf-8",
    )
    store = MarkdownRegistryStore(registry_path, ["primary"])

    entries = store.load()
    assert len(entries) == 1
    assert entries[0].part_index is None
    assert entries[0].total_parts is None
    assert entries[0].parent_file is None

    entries.append(
        RegistryEntry(
            file="video_part001.mp4",
            playlist="recordings",
            uploaded_date=date(2024, 1, 2),
            transcript_status=TranscriptStatus.PENDING,
            account_ids={"primary": "def456"},
            part_index=1,
            total_parts=2,
            parent_file="video.mp4",
        )
    )
    store._write_all(entries)

    content = registry_path.read_text(encoding="utf-8")
    assert "<!-- registry_version: 3 -->" in content
    assert "| Part |" in content

    reloaded = store.load()
    new_entry = next(entry for entry in reloaded if entry.file == "video_part001.mp4")
    assert new_entry.part_index == 1
    assert new_entry.total_parts == 2
    assert new_entry.parent_file == "video.mp4"
