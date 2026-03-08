from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from yt_recorder.adapters.registry import MarkdownRegistryStore
from yt_recorder.domain.models import RegistryEntry, TranscriptStatus


@pytest.fixture
def store(tmp_path: Path) -> MarkdownRegistryStore:
    return MarkdownRegistryStore(tmp_path / "registry.md", ["primary", "backup"])


def _entry(
    file: str = "video.mp4",
    account_ids: dict[str, str] | None = None,
    part_index: int | None = None,
    total_parts: int | None = None,
    parent_file: str | None = None,
) -> RegistryEntry:
    return RegistryEntry(
        file=file,
        playlist="root",
        uploaded_date=date(2026, 1, 15),
        transcript_status=TranscriptStatus.PENDING,
        account_ids=account_ids or {"primary": "—", "backup": "—"},
        part_index=part_index,
        total_parts=total_parts,
        parent_file=parent_file,
    )


class TestV2Compat:
    def test_v2_registry_loads_with_none_part_fields(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.md"
        v2_content = (
            "# Recordings Registry\n\n"
            "<!-- registry_version: 2 -->\n\n"
            "| File | Playlist | Uploaded | Transcript | primary | backup |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| video.mp4 | root | 2026-01-15 | pending | abc123 | xyz789 |\n"
        )
        registry_path.write_text(v2_content, encoding="utf-8")
        store = MarkdownRegistryStore(registry_path, ["primary", "backup"])

        entries = store.load()

        assert len(entries) == 1
        assert entries[0].part_index is None
        assert entries[0].total_parts is None
        assert entries[0].parent_file is None


class TestV3RoundTrip:
    def test_part_fields_preserved(self, store: MarkdownRegistryStore) -> None:
        entry = _entry(
            file="original_part1.mp4",
            account_ids={"primary": "vid1", "backup": "vid2"},
            part_index=1,
            total_parts=3,
            parent_file="original.mp4",
        )
        store.append(entry)

        entries = store.load()

        assert len(entries) == 1
        assert entries[0].part_index == 1
        assert entries[0].total_parts == 3
        assert entries[0].parent_file == "original.mp4"

    def test_none_part_fields_round_trip(self, store: MarkdownRegistryStore) -> None:
        entry = _entry(file="full.mp4", account_ids={"primary": "vid1", "backup": "vid2"})
        store.append(entry)

        entries = store.load()

        assert entries[0].part_index is None
        assert entries[0].total_parts is None
        assert entries[0].parent_file is None

    def test_header_has_part_columns(self, store: MarkdownRegistryStore) -> None:
        store._create_registry()
        content = store.registry_path.read_text()
        assert "| Part |" in content
        assert "| Total |" in content
        assert "| Parent |" in content

    def test_multiple_parts_round_trip(self, store: MarkdownRegistryStore) -> None:
        for i in range(1, 4):
            store.append(
                _entry(
                    file=f"original_part{i}.mp4",
                    account_ids={"primary": f"vid{i}", "backup": f"bak{i}"},
                    part_index=i,
                    total_parts=3,
                    parent_file="original.mp4",
                )
            )

        entries = store.load()

        assert len(entries) == 3
        for i, e in enumerate(entries, 1):
            assert e.part_index == i
            assert e.total_parts == 3
            assert e.parent_file == "original.mp4"


class TestGetPartsForParent:
    def test_returns_matching_parts(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="original.mp4", account_ids={"primary": "orig", "backup": "—"}))
        store.append(
            _entry(
                file="original_part1.mp4",
                account_ids={"primary": "p1", "backup": "—"},
                part_index=1,
                total_parts=2,
                parent_file="original.mp4",
            )
        )
        store.append(
            _entry(
                file="original_part2.mp4",
                account_ids={"primary": "p2", "backup": "—"},
                part_index=2,
                total_parts=2,
                parent_file="original.mp4",
            )
        )
        store.append(
            _entry(
                file="other_part1.mp4",
                account_ids={"primary": "o1", "backup": "—"},
                part_index=1,
                total_parts=1,
                parent_file="other.mp4",
            )
        )

        parts = store.get_parts_for_parent("original.mp4")

        assert len(parts) == 2
        assert all(e.parent_file == "original.mp4" for e in parts)
        files = {e.file for e in parts}
        assert files == {"original_part1.mp4", "original_part2.mp4"}

    def test_returns_empty_when_no_parts(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="video.mp4", account_ids={"primary": "v1", "backup": "—"}))

        parts = store.get_parts_for_parent("video.mp4")

        assert parts == []

    def test_returns_empty_when_registry_missing(self, tmp_path: Path) -> None:
        store = MarkdownRegistryStore(tmp_path / "missing.md", ["primary", "backup"])

        parts = store.get_parts_for_parent("original.mp4")

        assert parts == []


class TestIsAccountCovered:
    def test_true_when_original_has_video_id(self, store: MarkdownRegistryStore) -> None:
        store.append(
            _entry(file="video.mp4", account_ids={"primary": "vid123", "backup": "—"})
        )

        assert store.is_account_covered("video.mp4", "primary") is True

    def test_false_when_original_has_dash(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="video.mp4", account_ids={"primary": "—", "backup": "—"}))

        assert store.is_account_covered("video.mp4", "primary") is False

    def test_true_when_all_parts_have_video_id(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="original.mp4", account_ids={"primary": "—", "backup": "—"}))
        store.append(
            _entry(
                file="original_part1.mp4",
                account_ids={"primary": "—", "backup": "bak1"},
                part_index=1,
                total_parts=2,
                parent_file="original.mp4",
            )
        )
        store.append(
            _entry(
                file="original_part2.mp4",
                account_ids={"primary": "—", "backup": "bak2"},
                part_index=2,
                total_parts=2,
                parent_file="original.mp4",
            )
        )

        assert store.is_account_covered("original.mp4", "backup") is True

    def test_false_when_only_some_parts_have_video_id(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="original.mp4", account_ids={"primary": "—", "backup": "—"}))
        store.append(
            _entry(
                file="original_part1.mp4",
                account_ids={"primary": "—", "backup": "bak1"},
                part_index=1,
                total_parts=2,
                parent_file="original.mp4",
            )
        )
        store.append(
            _entry(
                file="original_part2.mp4",
                account_ids={"primary": "—", "backup": "—"},
                part_index=2,
                total_parts=2,
                parent_file="original.mp4",
            )
        )

        assert store.is_account_covered("original.mp4", "backup") is False

    def test_false_when_no_parts_and_original_missing_id(
        self, store: MarkdownRegistryStore
    ) -> None:
        store.append(_entry(file="original.mp4", account_ids={"primary": "—", "backup": "—"}))

        assert store.is_account_covered("original.mp4", "backup") is False

    def test_false_when_file_not_in_registry(self, store: MarkdownRegistryStore) -> None:
        store.append(_entry(file="other.mp4", account_ids={"primary": "v1", "backup": "v2"}))

        assert store.is_account_covered("missing.mp4", "primary") is False

    def test_false_when_registry_missing(self, tmp_path: Path) -> None:
        store = MarkdownRegistryStore(tmp_path / "missing.md", ["primary", "backup"])

        assert store.is_account_covered("video.mp4", "primary") is False
