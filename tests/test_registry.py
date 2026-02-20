from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from yt_recorder.adapters.registry import MarkdownRegistryStore
from yt_recorder.domain.exceptions import (
    RegistryFileNotFoundError,
    RegistryWriteError,
)
from yt_recorder.domain.models import RegistryEntry


@pytest.fixture
def temp_registry_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def registry_store(temp_registry_dir: Path) -> MarkdownRegistryStore:
    registry_path = temp_registry_dir / "registry.md"
    return MarkdownRegistryStore(registry_path, ["primary", "mirror-1"])


class TestRegistryEntry:
    def test_create_entry(self) -> None:
        entry = RegistryEntry(
            file="folder-a/video1.mp4",
            playlist="folder-a",
            uploaded_date=date(2026, 1, 15),
            has_transcript=True,
            account_ids={"primary": "abc123", "mirror-1": "xyz789"},
        )

        assert entry.file == "folder-a/video1.mp4"
        assert entry.playlist == "folder-a"
        assert entry.uploaded_date == date(2026, 1, 15)
        assert entry.has_transcript is True
        assert entry.account_ids == {"primary": "abc123", "mirror-1": "xyz789"}

    def test_entry_frozen(self) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={},
        )

        with pytest.raises(AttributeError):
            entry.file = "other.mp4"


class TestMarkdownRegistryStore:
    def test_create_registry(self, registry_store: MarkdownRegistryStore) -> None:
        registry_store._create_registry()

        assert registry_store.registry_path.exists()
        content = registry_store.registry_path.read_text()
        assert "# Recordings Registry" in content
        assert "| File | Playlist | Uploaded | Transcript | primary | mirror-1 |" in content

    def test_append_entry(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="folder-a/video1.mp4",
            playlist="folder-a",
            uploaded_date=date(2026, 1, 15),
            has_transcript=True,
            account_ids={"primary": "abc123", "mirror-1": "xyz789"},
        )

        registry_store.append(entry)

        assert registry_store.registry_path.exists()
        content = registry_store.registry_path.read_text()
        assert "folder-a/video1.mp4" in content
        assert "abc123" in content
        assert "xyz789" in content
        assert "✅" in content

    def test_load_entries(self, registry_store: MarkdownRegistryStore) -> None:
        entry1 = RegistryEntry(
            file="folder-a/video1.mp4",
            playlist="folder-a",
            uploaded_date=date(2026, 1, 15),
            has_transcript=True,
            account_ids={"primary": "abc123", "mirror-1": "xyz789"},
        )
        entry2 = RegistryEntry(
            file="folder-b/video2.mp4",
            playlist="folder-b",
            uploaded_date=date(2026, 1, 16),
            has_transcript=False,
            account_ids={"primary": "def456"},
        )

        registry_store.append(entry1)
        registry_store.append(entry2)

        entries = registry_store.load()

        assert len(entries) == 2
        assert entries[0].file == "folder-a/video1.mp4"
        assert entries[0].has_transcript is True
        assert entries[1].file == "folder-b/video2.mp4"
        assert entries[1].has_transcript is False

    def test_load_nonexistent_registry(self, registry_store: MarkdownRegistryStore) -> None:
        with pytest.raises(RegistryFileNotFoundError):
            registry_store.load()

    def test_is_registered(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )

        registry_store.append(entry)

        assert registry_store.is_registered("video.mp4") is True
        assert registry_store.is_registered("other.mp4") is False

    def test_is_registered_nonexistent_registry(
        self, registry_store: MarkdownRegistryStore
    ) -> None:
        assert registry_store.is_registered("video.mp4") is False

    def test_get_video_id(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123", "mirror-1": "xyz789"},
        )

        registry_store.append(entry)

        assert registry_store.get_video_id("video.mp4", "primary") == "abc123"
        assert registry_store.get_video_id("video.mp4", "mirror-1") == "xyz789"
        assert registry_store.get_video_id("video.mp4", "nonexistent") is None
        assert registry_store.get_video_id("other.mp4", "primary") is None

    def test_get_video_id_with_dash(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123", "mirror-1": "—"},
        )

        registry_store.append(entry)

        assert registry_store.get_video_id("video.mp4", "primary") == "abc123"
        assert registry_store.get_video_id("video.mp4", "mirror-1") is None

    def test_update_transcript(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )

        registry_store.append(entry)
        registry_store.update_transcript("video.mp4", True)

        entries = registry_store.load()
        assert entries[0].has_transcript is True

    def test_update_transcript_nonexistent(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )

        registry_store.append(entry)

        with pytest.raises(RegistryWriteError):
            registry_store.update_transcript("other.mp4", True)

    def test_round_trip_variable_columns(self, temp_registry_dir: Path) -> None:
        registry_path = temp_registry_dir / "registry.md"
        store1 = MarkdownRegistryStore(registry_path, ["primary", "mirror-1"])

        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=True,
            account_ids={"primary": "abc123", "mirror-1": "xyz789"},
        )

        store1.append(entry)

        store2 = MarkdownRegistryStore(registry_path, ["primary", "mirror-1", "mirror-2"])
        entries = store2.load()

        assert len(entries) == 1
        assert entries[0].file == "video.mp4"
        assert entries[0].account_ids["primary"] == "abc123"
        assert entries[0].account_ids["mirror-1"] == "xyz789"

    def test_relative_path_keying(self, registry_store: MarkdownRegistryStore) -> None:
        entry1 = RegistryEntry(
            file="folder-a/video.mp4",
            playlist="folder-a",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )
        entry2 = RegistryEntry(
            file="folder-b/video.mp4",
            playlist="folder-b",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "def456"},
        )

        registry_store.append(entry1)
        registry_store.append(entry2)

        assert registry_store.get_video_id("folder-a/video.mp4", "primary") == "abc123"
        assert registry_store.get_video_id("folder-b/video.mp4", "primary") == "def456"

    def test_atomic_write_crash_safety(self, temp_registry_dir: Path) -> None:
        registry_path = temp_registry_dir / "registry.md"
        store = MarkdownRegistryStore(registry_path, ["primary"])

        entry1 = RegistryEntry(
            file="video1.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )

        store.append(entry1)
        original_content = registry_path.read_text()

        entry2 = RegistryEntry(
            file="video2.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 16),
            has_transcript=False,
            account_ids={"primary": "def456"},
        )

        store.append(entry2)
        new_content = registry_path.read_text()

        assert "video1.mp4" in new_content
        assert "video2.mp4" in new_content
        assert len(new_content) > len(original_content)

    def test_multiple_accounts_in_row(self, temp_registry_dir: Path) -> None:
        registry_path = temp_registry_dir / "registry.md"
        store = MarkdownRegistryStore(
            registry_path, ["primary", "mirror-1", "mirror-2", "mirror-3"]
        )

        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=True,
            account_ids={
                "primary": "id1",
                "mirror-1": "id2",
                "mirror-2": "—",
                "mirror-3": "id4",
            },
        )

        store.append(entry)
        entries = store.load()

        assert len(entries) == 1
        assert entries[0].account_ids["primary"] == "id1"
        assert entries[0].account_ids["mirror-1"] == "id2"
        assert entries[0].account_ids["mirror-3"] == "id4"

    def test_update_account_id(self, registry_store: MarkdownRegistryStore) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123", "mirror-1": "—"},
        )
        registry_store.append(entry)

        registry_store.update_account_id("video.mp4", "mirror-1", "new789")

        entries = registry_store.load()
        assert entries[0].account_ids["mirror-1"] == "new789"
        assert entries[0].account_ids["primary"] == "abc123"

    def test_update_account_id_nonexistent(
        self, registry_store: MarkdownRegistryStore,
    ) -> None:
        entry = RegistryEntry(
            file="video.mp4",
            playlist="root",
            uploaded_date=date(2026, 1, 15),
            has_transcript=False,
            account_ids={"primary": "abc123"},
        )
        registry_store.append(entry)

        with pytest.raises(RegistryWriteError):
            registry_store.update_account_id("other.mp4", "primary", "new123")
