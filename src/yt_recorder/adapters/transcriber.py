from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

from yt_recorder.domain.exceptions import (
    SessionExpiredError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
)

logger = logging.getLogger(__name__)

# YouTube video IDs are an 11-char base64url subset. Anything else either
# means a registry parse glitch or an attempted URL injection via tampered
# registry rows. Refuse early before interpolating into a watch URL.
_VIDEO_ID_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _validate_video_id(video_id: str) -> None:
    if not _VIDEO_ID_RE.match(video_id):
        raise ValueError(f"Invalid YouTube video id: {video_id!r}")


class YtdlpTranscriptAdapter:
    """Extract transcripts from private YouTube videos using yt-dlp + cookies."""

    def __init__(self, cookies_path: Path, output_dir: Path) -> None:
        """Initialize adapter with cookies and output directory.

        Args:
            cookies_path: Path to Netscape-format cookies.txt file
            output_dir: Directory to save downloaded SRT files
        """
        self.cookies_path = cookies_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(self.output_dir), 0o700)
        except OSError:
            pass
        # Lazy-cached YoutubeDL instance. yt-dlp's YoutubeDL is reusable
        # across multiple `download()` calls and re-instantiating per-fetch
        # paid the cookie-file load cost on every call. Cache and reuse.
        # Keyed on the requested language so a switch between e.g. 'en' and
        # 'es' transparently rebuilds the instance.
        self._ydl: YoutubeDL | None = None
        self._ydl_lang: str | None = None

    def _get_or_create_ydl(self, lang: str) -> YoutubeDL:
        if self._ydl is not None and self._ydl_lang == lang:
            return self._ydl
        ydl_opts: dict[str, Any] = {
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "srt",
            "skip_download": True,
            "cookiefile": str(self.cookies_path),
            "outtmpl": str(self.output_dir / "%(id)s"),
            "quiet": True,
            "no_warnings": True,
        }
        self._ydl = YoutubeDL(ydl_opts)
        self._ydl_lang = lang
        return self._ydl

    def fetch(self, video_id: str, lang: str = "en") -> Path:
        """Download auto-generated subtitles as SRT file.

        Args:
            video_id: YouTube video ID (validated against `^[A-Za-z0-9_-]{11}$`)
            lang: Language code (default: "en")

        Returns:
            Path to downloaded SRT file

        Raises:
            ValueError: video_id fails format validation
            TranscriptNotReadyError: Captions still processing
            TranscriptUnavailableError: No captions exist
            SessionExpiredError: Cookies invalid/expired
        """
        _validate_video_id(video_id)
        ydl = self._get_or_create_ydl(lang)

        try:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as e:
            error_msg = str(e).lower()

            if "no subtitles" in error_msg or "no captions" in error_msg:
                raise TranscriptUnavailableError(
                    f"No captions available for video {video_id}"
                ) from e

            if "not available" in error_msg or "processing" in error_msg:
                raise TranscriptNotReadyError(
                    f"Captions still processing for video {video_id}"
                ) from e

            if "cookie" in error_msg or "authentication" in error_msg:
                raise SessionExpiredError(
                    f"Session expired or invalid cookies for video {video_id}"
                ) from e

            raise

        srt_file = self.output_dir / f"{video_id}.{lang}.srt"
        if not srt_file.exists():
            raise TranscriptUnavailableError(f"SRT file not created for video {video_id}")

        # SRT files contain transcript text from private videos. Treat as
        # owner-only at rest. The .tmp parent dir is locked down at adapter
        # init time, but the SRT files are created by yt-dlp under default
        # umask — re-chmod here before the caller reads them.
        try:
            os.chmod(str(srt_file), 0o600)
        except OSError:
            pass

        return srt_file

    def extract_cookies(self, storage_state_path: Path) -> Path:
        """Convert Playwright storage_state.json to Netscape cookies.txt format.

        Writes directly to ``self.cookies_path`` so subsequent ``fetch()``
        calls see the regenerated cookies. The previous version wrote to a
        sibling location and was silently ignored, leaving yt-dlp reading
        stale cookies from setup time.

        Args:
            storage_state_path: Path to Playwright storage_state.json

        Returns:
            Path to generated cookies.txt file (same as ``self.cookies_path``)

        Raises:
            SessionExpiredError: If storage_state is invalid or session-only
        """
        try:
            with open(storage_state_path, encoding="utf-8") as f:
                storage_state = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            raise SessionExpiredError(
                f"Invalid or missing storage_state at {storage_state_path}"
            ) from e

        cookies = storage_state.get("cookies", [])
        if not cookies:
            raise SessionExpiredError("No cookies found in storage_state")

        cookies_txt_path = self.cookies_path
        cookies_txt_path.parent.mkdir(parents=True, exist_ok=True)

        # Track future-expiry persistent cookies. If none of the cookies survive
        # past "right now", the session is effectively dead and yt-dlp will fail
        # with a confusing "Private video. Sign in" error — fail loud here instead.
        now = time.time()
        persistent_cookies = 0

        with open(cookies_txt_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file!  Do not edit.\n\n")

            for cookie in cookies:
                domain = cookie.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = cookie.get("path", "/")
                secure = "TRUE" if cookie.get("secure", False) else "FALSE"
                # Playwright encodes session cookies as expires=-1; the
                # Netscape spec requires 0 (or a positive unix ts). yt-dlp
                # rejects -1 with "invalid expires at -1".
                expires_raw = cookie.get("expires", 0)
                try:
                    expires_int = int(expires_raw)
                except (TypeError, ValueError):
                    expires_int = 0
                if expires_int <= 0:
                    expires = "0"
                else:
                    expires = str(expires_int)
                    if expires_int > now:
                        persistent_cookies += 1
                name = cookie.get("name", "")
                value = cookie.get("value", "")

                line = f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
                f.write(line)

        os.chmod(str(cookies_txt_path), 0o600)

        if persistent_cookies == 0:
            # Don't put the credential file path in the user-facing exception
            # — it lands in the JSONL log which other code reads. Log the
            # path at DEBUG only so it's still recoverable for support.
            logger.debug(
                "session-only cookies",
                extra={
                    "event": "session_only_cookies",
                    "storage_state_path": str(storage_state_path),
                },
            )
            raise SessionExpiredError(
                "Session-only cookies; re-run: yt-recorder setup --account <name>"
            )

        return cookies_txt_path

    def cleanup(self) -> None:
        """Clean up temporary output directory and all files within.

        Called after processing is complete to remove accumulated SRT files
        and other temporary artifacts.
        """
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir, ignore_errors=True)
