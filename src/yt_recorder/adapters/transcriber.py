from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

from yt_recorder.domain.exceptions import (
    SessionExpiredError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
)


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

    def fetch(self, video_id: str, lang: str = "en") -> Path:
        """Download auto-generated subtitles as SRT file.

        Args:
            video_id: YouTube video ID
            lang: Language code (default: "en")

        Returns:
            Path to downloaded SRT file

        Raises:
            TranscriptNotReadyError: Captions still processing
            TranscriptUnavailableError: No captions exist
            SessionExpiredError: Cookies invalid/expired
        """
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

        try:
            with YoutubeDL(ydl_opts) as ydl:
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

        return srt_file

    def extract_cookies(self, storage_state_path: Path) -> Path:
        """Convert Playwright storage_state.json to Netscape cookies.txt format.

        Args:
            storage_state_path: Path to Playwright storage_state.json

        Returns:
            Path to generated cookies.txt file

        Raises:
            SessionExpiredError: If storage_state is invalid
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

        cookies_txt_path = self.output_dir / "cookies.txt"

        with open(cookies_txt_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file!  Do not edit.\n\n")

            for cookie in cookies:
                domain = cookie.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = cookie.get("path", "/")
                secure = "TRUE" if cookie.get("secure", False) else "FALSE"
                expires = str(int(cookie.get("expires", 0)))
                name = cookie.get("name", "")
                value = cookie.get("value", "")

                line = f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
                f.write(line)

        return cookies_txt_path

    def cleanup(self) -> None:
        """Clean up temporary output directory and all files within.

        Called after processing is complete to remove accumulated SRT files
        and other temporary artifacts.
        """
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir, ignore_errors=True)
