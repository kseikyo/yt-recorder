from __future__ import annotations


class YTRecorderError(Exception):
    """Base exception for yt-recorder."""


class RegistryError(YTRecorderError):
    """Base exception for registry operations."""


class RegistryFileNotFoundError(RegistryError):
    """Registry file does not exist."""


class RegistryParseError(RegistryError):
    """Failed to parse registry markdown file."""


class RegistryWriteError(RegistryError):
    """Failed to write registry file."""


class TranscriptError(YTRecorderError):
    """Base exception for transcript operations."""


class TranscriptNotReadyError(TranscriptError):
    """Transcript captions still processing."""


class TranscriptUnavailableError(TranscriptError):
    """No captions exist for video."""


class SessionExpiredError(YTRecorderError):
    """Session/cookies invalid or expired."""


class YouTubeError(YTRecorderError):
    """Base exception for YouTube adapter operations."""


class BotDetectionError(YouTubeError):
    """CAPTCHA or challenge page detected."""


class VerificationRequiredError(YouTubeError):
    """Google requires identity verification (e.g. 'Verify it's you' dialog)."""


class ChannelCreationRequiredError(YouTubeError):
    pass


class UnsupportedBrowserError(YouTubeError):
    """YouTube rejected the browser as unsupported or outdated."""


class SelectorChangedError(YouTubeError):
    """YouTube UI selector not found (UI may have changed)."""


class UploadTimeoutError(YouTubeError):
    """Upload exceeded timeout."""


class DailyLimitError(YouTubeError):
    """Daily upload limit reached."""


class VideoTooLongError(YouTubeError):
    """Video exceeds account's duration limit."""

    def __init__(self, message: str, detected_limit_secs: float | None = None) -> None:
        super().__init__(message)
        self.detected_limit_secs = detected_limit_secs


class SplitterError(YTRecorderError):
    """Failed to split video file."""
