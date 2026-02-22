"""Port interfaces for the hexagonal architecture.

These protocols define the contracts that adapters must implement.
They enable the pipeline to depend on abstractions rather than concrete classes,
making the system testable and extensible.

Protocols use structural typing (duck typing): adapters don't need to inherit
from these classes, they just need to implement the methods.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from yt_recorder.domain.models import RegistryEntry, UploadResult


@runtime_checkable
class VideoUploader(Protocol):
    """Port for uploading videos to a video hosting platform.

    Adapters: YouTubeBrowserAdapter
    """

    def open(self) -> None:
        """Open connection to the video hosting platform."""
        ...

    def close(self) -> None:
        """Close connection to the video hosting platform."""
        ...

    def upload(self, path: Path, title: str) -> UploadResult:
        """Upload a video file.

        Args:
            path: Path to the video file
            title: Title for the uploaded video

        Returns:
            UploadResult with video_id, url, title, and account_name
        """
        ...

    def assign_playlist(self, video_id: str, playlist_name: str) -> bool:
        """Assign an uploaded video to a playlist.

        Args:
            video_id: YouTube video ID
            playlist_name: Name of the playlist to assign to

        Returns:
            True if assignment succeeded, False otherwise
        """
        ...


@runtime_checkable
class TranscriptFetcher(Protocol):
    """Port for fetching transcripts from uploaded videos.

    Adapters: YtDlpTranscriptAdapter
    """

    def fetch(self, video_id: str, lang: str = ...) -> Path:
        """Fetch transcript for a video.

        Args:
            video_id: YouTube video ID
            lang: Language code for transcript (default varies by adapter)

        Returns:
            Path to the saved transcript file
        """
        ...


@runtime_checkable
class RegistryStore(Protocol):
    """Port for persisting the registry of uploaded videos.

    Adapters: MarkdownRegistryAdapter
    """

    def load(self) -> list[RegistryEntry]:
        """Load all registry entries.

        Returns:
            List of RegistryEntry objects
        """
        ...

    def append(self, entry: RegistryEntry) -> None:
        """Add a new entry to the registry.

        Args:
            entry: RegistryEntry to add
        """
        ...

    def update_transcript(self, file: str, status: bool) -> None:
        """Update transcript status for a file.

        Args:
            file: Relative path from recordings directory
            status: Whether transcript exists
        """
        ...

    def update_account_id(self, file: str, account: str, video_id: str) -> None:
        """Update the video ID for a specific account.

        Args:
            file: Relative path from recordings directory
            account: Account name
            video_id: YouTube video ID for this account
        """
        ...

    def update_many(self, updates: dict[str, dict[str, object]]) -> None:
        """Batch update multiple registry entries.

        Args:
            updates: Mapping of file paths to update dictionaries.
                     Each update dict contains field names and new values.
                     Example: {"video1.mp4": {"has_transcript": True}}
        """
        ...
