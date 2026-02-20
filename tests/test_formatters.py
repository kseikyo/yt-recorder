from __future__ import annotations

import pytest

from yt_recorder.domain.formatters import (
    format_timestamp,
    format_transcript_md,
    parse_srt,
    title_from_filename,
)
from yt_recorder.domain.models import TranscriptSegment


class TestTitleFromFilename:
    def test_strip_extension(self) -> None:
        assert title_from_filename("video.mp4") == "Video"

    def test_convert_dashes_to_spaces(self) -> None:
        assert title_from_filename("my-video-file.mp4") == "My Video File"

    def test_convert_underscores_to_spaces(self) -> None:
        assert title_from_filename("my_video_file.mp4") == "My Video File"

    def test_convert_mixed_dashes_underscores(self) -> None:
        assert title_from_filename("my-video_file.mp4") == "My Video File"

    def test_title_case(self) -> None:
        assert title_from_filename("hello-world.mp4") == "Hello World"

    def test_truncate_at_100_chars_with_word_boundary(self) -> None:
        long_name = "a" * 50 + "-" + "b" * 50 + ".mp4"
        result = title_from_filename(long_name)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_truncate_no_space_found(self) -> None:
        # Create a name that's > 100 chars with no spaces
        long_name = "a" * 105 + ".mp4"
        result = title_from_filename(long_name)
        assert len(result) == 100  # 97 + "..."
        assert result.endswith("...")

    def test_strip_control_characters(self) -> None:
        # Include a control character (null byte)
        name = "hello\x00world.mp4"
        result = title_from_filename(name)
        assert "\x00" not in result
        assert result == "HelloWorld"

    def test_strip_rtl_override(self) -> None:
        # RTL override character
        name = "hello\u202eworld.mp4"
        result = title_from_filename(name)
        assert "\u202e" not in result

    def test_strip_ltr_override(self) -> None:
        # LTR override character
        name = "hello\u202dworld.mp4"
        result = title_from_filename(name)
        assert "\u202d" not in result

    def test_reject_pipe_character(self) -> None:
        with pytest.raises(ValueError, match="pipe character"):
            title_from_filename("hello|world.mp4")

    def test_preserve_legitimate_unicode(self) -> None:
        # Accented characters should be preserved
        name = "café-résumé.mp4"
        result = title_from_filename(name)
        assert "café" in result.lower() or "cafe" in result.lower()

    def test_strip_trailing_whitespace(self) -> None:
        name = "  hello-world  .mp4"
        result = title_from_filename(name)
        assert result == result.strip()

    def test_multiple_consecutive_separators(self) -> None:
        assert title_from_filename("hello---world.mp4") == "Hello World"
        assert title_from_filename("hello___world.mp4") == "Hello World"


class TestFormatTimestamp:
    def test_format_seconds_only(self) -> None:
        assert format_timestamp(5.0) == "[00:05]"

    def test_format_minutes_seconds(self) -> None:
        assert format_timestamp(65.0) == "[01:05]"

    def test_format_hours_minutes_seconds(self) -> None:
        assert format_timestamp(3665.0) == "[1:01:05]"

    def test_format_zero(self) -> None:
        assert format_timestamp(0.0) == "[00:00]"

    def test_format_59_seconds(self) -> None:
        assert format_timestamp(59.0) == "[00:59]"

    def test_format_59_minutes_59_seconds(self) -> None:
        assert format_timestamp(3599.0) == "[59:59]"

    def test_format_1_hour(self) -> None:
        assert format_timestamp(3600.0) == "[1:00:00]"

    def test_format_multiple_hours(self) -> None:
        assert format_timestamp(7325.0) == "[2:02:05]"

    def test_truncate_fractional_seconds(self) -> None:
        # Fractional seconds should be truncated
        assert format_timestamp(5.999) == "[00:05]"


class TestParseSrt:
    def test_parse_single_entry(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000
First line of transcript
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].start == 0.0
        assert segments[0].end == 5.0
        assert segments[0].text == "First line of transcript"

    def test_parse_multiple_entries(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000
First line

2
00:00:05,000 --> 00:00:10,000
Second line
"""
        segments = parse_srt(srt)
        assert len(segments) == 2
        assert segments[0].text == "First line"
        assert segments[1].text == "Second line"

    def test_parse_multiline_text(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000
First line
of transcript
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].text == "First line of transcript"

    def test_parse_varying_newlines(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000
First line


2
00:00:05,000 --> 00:00:10,000
Second line
"""
        segments = parse_srt(srt)
        assert len(segments) == 2

    def test_parse_with_period_decimal_separator(self) -> None:
        srt = """1
00:00:00.000 --> 00:00:05.000
First line
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].start == 0.0
        assert segments[0].end == 5.0

    def test_parse_with_hours(self) -> None:
        srt = """1
01:30:45,500 --> 01:30:50,500
First line
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].start == pytest.approx(5445.5)
        assert segments[0].end == pytest.approx(5450.5)

    def test_parse_empty_content(self) -> None:
        segments = parse_srt("")
        assert len(segments) == 0

    def test_parse_malformed_entry_skipped(self) -> None:
        srt = """1
invalid timestamp
First line

2
00:00:05,000 --> 00:00:10,000
Second line
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].text == "Second line"

    def test_parse_entry_without_text_skipped(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000

2
00:00:05,000 --> 00:00:10,000
Second line
"""
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0].text == "Second line"


class TestFormatTranscriptMd:
    def test_format_single_segment(self) -> None:
        segments = [TranscriptSegment(start=0.0, end=5.0, text="First line")]
        result = format_transcript_md(segments, "https://youtu.be/abc123", "My Video")

        assert "# My Video" in result
        assert "Video: https://youtu.be/abc123" in result
        assert "## Transcript" in result
        assert "[00:00] First line" in result

    def test_format_multiple_segments(self) -> None:
        segments = [
            TranscriptSegment(start=0.0, end=5.0, text="First line"),
            TranscriptSegment(start=5.0, end=10.0, text="Second line"),
        ]
        result = format_transcript_md(segments, "https://youtu.be/abc123", "My Video")

        assert "[00:00] First line" in result
        assert "[00:05] Second line" in result

    def test_format_with_hours(self) -> None:
        segments = [TranscriptSegment(start=3665.0, end=3670.0, text="After one hour")]
        result = format_transcript_md(segments, "https://youtu.be/abc123", "My Video")

        assert "[1:01:05] After one hour" in result

    def test_format_empty_segments(self) -> None:
        result = format_transcript_md([], "https://youtu.be/abc123", "My Video")

        assert "# My Video" in result
        assert "Video: https://youtu.be/abc123" in result
        assert "## Transcript" in result

    def test_format_structure(self) -> None:
        segments = [TranscriptSegment(start=0.0, end=5.0, text="Line")]
        result = format_transcript_md(segments, "https://youtu.be/abc123", "My Video")

        lines = result.split("\n")
        assert lines[0] == "# My Video"
        assert lines[1] == ""
        assert "Video: https://youtu.be/abc123" in lines[2]
        assert "## Transcript" in result


class TestIntegration:
    def test_title_and_timestamp_together(self) -> None:
        title = title_from_filename("my-video-file.mp4")
        timestamp = format_timestamp(65.0)

        assert title == "My Video File"
        assert timestamp == "[01:05]"

    def test_parse_and_format_srt(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:05,000
First line

2
00:00:05,000 --> 00:00:10,000
Second line
"""
        segments = parse_srt(srt)
        result = format_transcript_md(segments, "https://youtu.be/abc123", "My Video")

        assert "[00:00] First line" in result
        assert "[00:05] Second line" in result
        assert "# My Video" in result
