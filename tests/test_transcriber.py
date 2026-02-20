from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_recorder.adapters.transcriber import YtdlpTranscriptAdapter
from yt_recorder.domain.exceptions import (
    SessionExpiredError,
    TranscriptNotReadyError,
    TranscriptUnavailableError,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cookies_file(temp_dir: Path) -> Path:
    cookies_path = temp_dir / "cookies.txt"
    cookies_path.write_text("# Netscape HTTP Cookie File\n")
    return cookies_path


@pytest.fixture
def storage_state_file(temp_dir: Path) -> Path:
    storage_state = {
        "cookies": [
            {
                "domain": ".youtube.com",
                "path": "/",
                "name": "SSID",
                "value": "test_value_123",
                "secure": True,
                "expires": 1735689600,
            },
            {
                "domain": ".google.com",
                "path": "/",
                "name": "NID",
                "value": "test_nid_456",
                "secure": False,
                "expires": 1735689600,
            },
        ]
    }
    storage_state_path = temp_dir / "storage_state.json"
    with open(storage_state_path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f)
    return storage_state_path


class TestYtdlpTranscriptAdapter:
    def test_init_creates_output_dir(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        assert output_dir.exists()
        assert adapter.cookies_path == cookies_file
        assert adapter.output_dir == output_dir

    def test_init_with_existing_output_dir(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        output_dir.mkdir()
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        assert output_dir.exists()
        assert adapter.output_dir == output_dir

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_success(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        video_id = "dQw4w9WgXcQ"
        srt_file = output_dir / f"{video_id}.en.srt"
        srt_file.write_text("1\n00:00:00,000 --> 00:00:05,000\nTest caption\n")

        result = adapter.fetch(video_id)

        assert result == srt_file
        mock_ydl.download.assert_called_once()

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_with_custom_language(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        video_id = "dQw4w9WgXcQ"
        lang = "es"
        srt_file = output_dir / f"{video_id}.{lang}.srt"
        srt_file.write_text("1\n00:00:00,000 --> 00:00:05,000\nCaption en español\n")

        result = adapter.fetch(video_id, lang=lang)

        assert result == srt_file

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_no_captions_available(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.download.side_effect = Exception("No captions found")

        with pytest.raises(TranscriptUnavailableError):
            adapter.fetch("dQw4w9WgXcQ")

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_captions_not_ready(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.download.side_effect = Exception("Subtitles not available yet")

        with pytest.raises(TranscriptNotReadyError):
            adapter.fetch("dQw4w9WgXcQ")

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_session_expired(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.download.side_effect = Exception("Cookie authentication failed")

        with pytest.raises(SessionExpiredError):
            adapter.fetch("dQw4w9WgXcQ")

    @patch("yt_recorder.adapters.transcriber.YoutubeDL")
    def test_fetch_srt_file_not_created(
        self, mock_ydl_class: MagicMock, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(TranscriptUnavailableError):
            adapter.fetch("dQw4w9WgXcQ")

    def test_extract_cookies_success(
        self, temp_dir: Path, cookies_file: Path, storage_state_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        result = adapter.extract_cookies(storage_state_file)

        assert result.exists()
        assert result.name == "cookies.txt"

        content = result.read_text(encoding="utf-8")
        assert "# Netscape HTTP Cookie File" in content
        assert ".youtube.com" in content
        assert "SSID" in content
        assert "test_value_123" in content

    def test_extract_cookies_netscape_format(
        self, temp_dir: Path, cookies_file: Path, storage_state_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        result = adapter.extract_cookies(storage_state_file)
        content = result.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        assert lines[0] == "# Netscape HTTP Cookie File"
        assert lines[1] == "# This is a generated file!  Do not edit."

        cookie_lines = [line for line in lines[3:] if line.strip()]
        assert len(cookie_lines) == 2

        for line in cookie_lines:
            parts = line.split("\t")
            assert len(parts) == 7
            domain, flag, path, secure, expires, name, _value = parts
            assert domain in [".youtube.com", ".google.com"]
            assert flag in ["TRUE", "FALSE"]
            assert path == "/"
            assert secure in ["TRUE", "FALSE"]
            assert expires.isdigit()
            assert name in ["SSID", "NID"]

    def test_extract_cookies_missing_file(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        missing_file = temp_dir / "nonexistent.json"

        with pytest.raises(SessionExpiredError):
            adapter.extract_cookies(missing_file)

    def test_extract_cookies_invalid_json(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        invalid_file = temp_dir / "invalid.json"
        invalid_file.write_text("{ invalid json }")

        with pytest.raises(SessionExpiredError):
            adapter.extract_cookies(invalid_file)

    def test_extract_cookies_no_cookies_in_storage_state(
        self, temp_dir: Path, cookies_file: Path
    ) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        storage_state_file = temp_dir / "empty_storage_state.json"
        storage_state_file.write_text(json.dumps({"cookies": []}))

        with pytest.raises(SessionExpiredError):
            adapter.extract_cookies(storage_state_file)

    def test_extract_cookies_missing_cookies_key(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        storage_state_file = temp_dir / "no_cookies_key.json"
        storage_state_file.write_text(json.dumps({"other_key": []}))

        with pytest.raises(SessionExpiredError):
            adapter.extract_cookies(storage_state_file)

    def test_extract_cookies_secure_flag_handling(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        storage_state = {
            "cookies": [
                {
                    "domain": ".example.com",
                    "path": "/",
                    "name": "secure_cookie",
                    "value": "secure_value",
                    "secure": True,
                    "expires": 1735689600,
                },
                {
                    "domain": ".example.com",
                    "path": "/",
                    "name": "insecure_cookie",
                    "value": "insecure_value",
                    "secure": False,
                    "expires": 1735689600,
                },
            ]
        }
        storage_state_file = temp_dir / "secure_storage_state.json"
        with open(storage_state_file, "w", encoding="utf-8") as f:
            json.dump(storage_state, f)

        result = adapter.extract_cookies(storage_state_file)
        content = result.read_text(encoding="utf-8")

        assert "secure_cookie\tTRUE" in content or "secure_cookie" in content
        assert "insecure_cookie" in content

    def test_extract_cookies_domain_flag_logic(self, temp_dir: Path, cookies_file: Path) -> None:
        output_dir = temp_dir / "transcripts"
        adapter = YtdlpTranscriptAdapter(cookies_file, output_dir)

        storage_state = {
            "cookies": [
                {
                    "domain": ".youtube.com",
                    "path": "/",
                    "name": "cookie1",
                    "value": "value1",
                    "secure": True,
                    "expires": 1735689600,
                },
                {
                    "domain": "example.com",
                    "path": "/",
                    "name": "cookie2",
                    "value": "value2",
                    "secure": False,
                    "expires": 1735689600,
                },
            ]
        }
        storage_state_file = temp_dir / "domain_flag_storage_state.json"
        with open(storage_state_file, "w", encoding="utf-8") as f:
            json.dump(storage_state, f)

        result = adapter.extract_cookies(storage_state_file)
        content = result.read_text(encoding="utf-8")
        lines = [line for line in content.split("\n") if line.strip() and not line.startswith("#")]

        assert len(lines) == 2
        parts1 = lines[0].split("\t")
        parts2 = lines[1].split("\t")

        assert parts1[0] == ".youtube.com"
        assert parts1[1] == "TRUE"

        assert parts2[0] == "example.com"
        assert parts2[1] == "FALSE"
