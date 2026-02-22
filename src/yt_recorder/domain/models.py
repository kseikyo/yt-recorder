from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class TranscriptSegment:
    """A single segment from a transcript (SRT format).

    Attributes:
        start: Start time in seconds
        end: End time in seconds
        text: Transcript text for this segment
    """

    start: float
    end: float
    text: str


class TranscriptStatus(str, Enum):
    """Transcript extraction status.

    States:
        PENDING: Transcript not yet requested/available
        DONE: Transcript successfully fetched
        UNAVAILABLE: YouTube says no transcript exists
        ERROR: Fetch failed with error (retryable with --retry flag)
    """

    PENDING = "pending"
    DONE = "done"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class RegistryEntry:
    """Registry entry for a recorded video.

    Attributes:
        file: Relative path from recordings directory (e.g., "folder-a/video1.mp4")
        playlist: Folder→playlist name (e.g., "folder-a")
        uploaded_date: Date when video was uploaded
        transcript_status: Transcript extraction status
        account_ids: Mapping of account names to YouTube video IDs
                     (e.g., {"primary": "abc123", "mirror-1": "xyz789"})
    """

    file: str
    playlist: str
    uploaded_date: date
    transcript_status: TranscriptStatus
    account_ids: dict[str, str]

    @property
    def has_transcript(self) -> bool:
        """Backwards-compat: True when transcript done."""
        return self.transcript_status == TranscriptStatus.DONE


@dataclass(frozen=True)
class YouTubeAccount:
    """YouTube account credentials and configuration.

    Attributes:
        name: Account identifier (e.g., "primary", "mirror-1")
        storage_state: Path to Playwright storage_state.json file
        cookies_path: Path to Netscape cookies.txt file
        role: Account role (e.g., "primary", "mirror")
    """

    name: str
    storage_state: Path
    cookies_path: Path
    role: str


@dataclass(frozen=True)
class UploadResult:
    """Result of a single video upload.

    Attributes:
        video_id: YouTube video ID
        url: Full YouTube video URL
        title: Video title as uploaded
        account_name: Account name that performed upload
    """

    video_id: str
    url: str
    title: str
    account_name: str


@dataclass(frozen=True)
class FileUploadResult:
    """Per-file result from an upload batch.

    Attributes:
        file: Relative path from recordings directory
        title: Humanized title used for upload
        account_results: Mapping of account names to video IDs or "—" for failures
        deleted: Whether local file was deleted after upload
    """

    file: str
    title: str
    account_results: dict[str, str]
    deleted: bool


@dataclass(frozen=True)
class CleanReport:
    """Report from clean_synced() operation."""

    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    eligible: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncReport:
    """Report of upload/transcript sync operation."""

    uploaded: int = 0
    skipped: int = 0
    upload_failed: int = 0
    deleted_count: int = 0
    kept_count: int = 0
    delete_failed: int = 0
    transcripts_fetched: int = 0
    transcripts_pending: int = 0
    playlist_failed: int = 0
    total_registered: int = 0
    account_stats: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
