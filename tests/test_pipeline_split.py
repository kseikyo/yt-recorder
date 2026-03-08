from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast
from unittest.mock import Mock, call, patch

from yt_recorder.adapters.splitter import TIER_1HR, TIER_15MIN
from yt_recorder.config import Config
from yt_recorder.domain.exceptions import DailyLimitError, VideoTooLongError
from yt_recorder.domain.models import RegistryEntry, TranscriptStatus, UploadResult, YouTubeAccount
from yt_recorder.pipeline import RecordingPipeline


class InMemoryRegistry:
    def __init__(self, entries: list[RegistryEntry] | None = None) -> None:
        self.entries = list(entries or [])

    def load(self) -> list[RegistryEntry]:
        return list(self.entries)

    def append(self, entry: RegistryEntry) -> None:
        self.entries.append(entry)

    def get_parts_for_parent(self, parent_file: str) -> list[RegistryEntry]:
        return [e for e in self.entries if e.parent_file == parent_file]

    def is_account_covered(self, file: str, account_name: str) -> bool:
        original = next((e for e in self.entries if e.file == file and e.part_index is None), None)
        if original is None:
            return False
        if original.account_ids.get(account_name, "—") != "—":
            return True
        parts = [e for e in self.entries if e.parent_file == file]
        if not parts:
            return False
        return all(e.account_ids.get(account_name, "—") != "—" for e in parts)

    def update_account_id(self, file: str, account: str, video_id: str) -> None:
        for idx, entry in enumerate(self.entries):
            if entry.file == file:
                new_ids = dict(entry.account_ids)
                new_ids[account] = video_id
                self.entries[idx] = RegistryEntry(
                    file=entry.file,
                    playlist=entry.playlist,
                    uploaded_date=entry.uploaded_date,
                    transcript_status=entry.transcript_status,
                    account_ids=new_ids,
                    part_index=entry.part_index,
                    total_parts=entry.total_parts,
                    parent_file=entry.parent_file,
                )
                return

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

    def update_transcript(self, file: str, status: TranscriptStatus) -> None:
        for idx, entry in enumerate(self.entries):
            if entry.file == file:
                self.entries[idx] = RegistryEntry(
                    file=entry.file,
                    playlist=entry.playlist,
                    uploaded_date=entry.uploaded_date,
                    transcript_status=status,
                    account_ids=entry.account_ids,
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


def _result(video_id: str, account_name: str) -> UploadResult:
    return UploadResult(video_id, f"https://youtu.be/{video_id}", "title", account_name)


def test_upload_new_full_primary_split_backup(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    parts_dir = tmp_path / ".video_parts"
    parts_dir.mkdir()
    parts = [parts_dir / f"video_part00{i}.mp4" for i in range(1, 4)]
    for part in parts:
        part.write_text("x")

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
            return _result("p1", account_name)
        return _result(f"b{upload_path.stem[-1]}", account_name)

    raid.upload_to_account.side_effect = upload_side_effect

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "root")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter = splitter_cls.return_value
            splitter.get_duration.return_value = 7200.0
            splitter.split.return_value = parts

            pipeline = RecordingPipeline(_config(accounts), registry, raid)
            report = pipeline.upload_new(tmp_path)

    assert report.uploaded == 1
    assert len(registry.entries) == 4

    original = next(e for e in registry.entries if e.file == "video.mp4")
    assert original.account_ids == {"primary": "p1", "backup": "—"}

    part_entries = [e for e in registry.entries if e.parent_file == "video.mp4"]
    assert len(part_entries) == 3
    assert [e.part_index for e in part_entries] == [1, 2, 3]
    assert all(e.total_parts == 3 for e in part_entries)
    assert all(e.account_ids.get("backup", "—") != "—" for e in part_entries)


def test_upload_new_daily_limit_stops_all_files(tmp_path: Path) -> None:
    path_a = tmp_path / "a.mp4"
    path_b = tmp_path / "b.mp4"
    path_a.write_text("x")
    path_b.write_text("x")

    accounts = [
        YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
        YouTubeAccount("backup", Path("/tmp/b.json"), Path("/tmp/b.txt"), "mirror"),
    ]
    registry = InMemoryRegistry()
    raid = Mock()
    raid.primary = accounts[0]
    raid.mirrors = [accounts[1]]
    raid.assign_playlist_to_account.return_value = True
    raid.upload_to_account.side_effect = [
        _result("p1", "primary"),
        DailyLimitError("limit"),
    ]

    with patch(
        "yt_recorder.pipeline.scan_recordings", return_value=[(path_a, "root"), (path_b, "root")]
    ):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter_cls.return_value.get_duration.return_value = 100.0
            pipeline = RecordingPipeline(_config(accounts), registry, raid)
            report = pipeline.upload_new(tmp_path)

    assert report.uploaded == 1
    assert len(registry.entries) == 1
    assert registry.entries[0].file == "a.mp4"
    assert registry.entries[0].account_ids == {"primary": "p1", "backup": "—"}
    assert raid.upload_to_account.call_count == 2


def test_clean_synced_checks_account_coverage(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    parts_dir = tmp_path / ".video_parts"
    parts_dir.mkdir()
    part_1 = parts_dir / "video_part001.mp4"
    part_1.write_text("x")

    accounts = [
        YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
        YouTubeAccount("backup", Path("/tmp/b.json"), Path("/tmp/b.txt"), "mirror"),
    ]

    entry = RegistryEntry(
        file="video.mp4",
        playlist="root",
        uploaded_date=date.today(),
        transcript_status=TranscriptStatus.DONE,
        account_ids={"primary": "abc", "backup": "—"},
    )
    registry = Mock()
    registry.load.return_value = [entry]
    registry.is_account_covered.side_effect = lambda file, account: account == "primary"

    with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
        splitter = splitter_cls.return_value
        pipeline = RecordingPipeline(_config(accounts), registry, Mock())

        report_partial = pipeline.clean_synced(tmp_path)
        assert report_partial.deleted == 0
        assert report_partial.skipped == 1
        assert path.exists()

        registry.is_account_covered.side_effect = lambda file, account: True
        report_full = pipeline.clean_synced(tmp_path)
        assert report_full.deleted == 1
        assert not path.exists()
        splitter.cleanup_parts.assert_called_once_with([part_1])


def test_upload_new_non_split_behavior_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    accounts = [
        YouTubeAccount("primary", Path("/tmp/p.json"), Path("/tmp/p.txt"), "primary"),
        YouTubeAccount("mirror", Path("/tmp/m.json"), Path("/tmp/m.txt"), "mirror"),
    ]
    registry = InMemoryRegistry()
    raid = Mock()
    raid.primary = accounts[0]
    raid.mirrors = [accounts[1]]
    raid.assign_playlist_to_account.return_value = True
    raid.upload_to_account.side_effect = [
        _result("p1", "primary"),
        _result("m1", "mirror"),
    ]

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "root")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter = splitter_cls.return_value
            splitter.get_duration.return_value = 120.0

            pipeline = RecordingPipeline(_config(accounts), registry, raid)
            report = pipeline.upload_new(tmp_path)

    assert report.uploaded == 1
    assert report.deleted_count == 1
    assert not path.exists()
    assert len(registry.entries) == 1
    assert registry.entries[0].account_ids == {"primary": "p1", "mirror": "m1"}
    splitter.split.assert_not_called()


def test_upload_new_crash_recovery_uploads_only_missing_parts(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    parts_dir = tmp_path / ".video_parts"
    parts_dir.mkdir()
    part_1 = parts_dir / "video_part001.mp4"
    part_2 = parts_dir / "video_part002.mp4"
    part_3 = parts_dir / "video_part003.mp4"
    for part in [part_1, part_2, part_3]:
        part.write_text("x")

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
    existing_part_entry = RegistryEntry(
        file=str(part_1.relative_to(tmp_path)),
        playlist="root",
        uploaded_date=date.today(),
        transcript_status=TranscriptStatus.PENDING,
        account_ids={"backup": "b1"},
        part_index=1,
        total_parts=3,
        parent_file="video.mp4",
    )
    registry = InMemoryRegistry([existing_part_entry])
    raid = Mock()
    raid.primary = accounts[0]
    raid.mirrors = [accounts[1]]
    raid.assign_playlist_to_account.return_value = True
    raid.upload_to_account.side_effect = [
        _result("p1", "primary"),
        _result("b2", "backup"),
        _result("b3", "backup"),
    ]

    with patch("yt_recorder.pipeline.scan_recordings", return_value=[(path, "root")]):
        with patch("yt_recorder.adapters.splitter.VideoSplitter") as splitter_cls:
            splitter = splitter_cls.return_value
            splitter.get_duration.return_value = 7200.0

            pipeline = RecordingPipeline(_config(accounts), registry, raid)
            report = pipeline.upload_new(tmp_path)

    assert report.uploaded == 1
    assert raid.upload_to_account.call_count == 3
    backup_calls = [c for c in raid.upload_to_account.call_args_list if c.args[0] == "backup"]
    assert [c.args[1] for c in backup_calls] == [part_2, part_3]
    splitter.split.assert_not_called()


def test_detect_tier_falls_back_from_1hr_to_15min(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_text("x")

    accounts = [YouTubeAccount("backup", Path("/tmp/b.json"), Path("/tmp/b.txt"), "mirror")]
    pipeline = RecordingPipeline(_config(accounts), InMemoryRegistry(), Mock())

    parts_1hr = [tmp_path / "p1.mp4"]
    parts_15m = [tmp_path / "p2.mp4"]
    splitter = Mock()
    splitter.split.side_effect = [parts_1hr, parts_15m]
    raid = Mock()

    with patch.object(
        pipeline,
        "_upload_parts_to_account",
        side_effect=[VideoTooLongError("too long"), None],
    ) as upload_parts:
        detected = pipeline._detect_tier(
            raid=raid,
            splitter=splitter,
            account=accounts[0],
            path=path,
            title="title",
            playlist="root",
            directory=tmp_path,
            registry=InMemoryRegistry(),
        )

    assert detected == TIER_15MIN
    assert splitter.split.call_args_list == [
        call(path, TIER_1HR),
        call(path, TIER_15MIN),
    ]
    splitter.cleanup_parts.assert_called_once_with(parts_1hr)
    assert upload_parts.call_count == 2
