from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TranscriptSegment


def title_from_filename(filename: str) -> str:
    """Convert filename to humanized title.

    - Strip extension
    - Convert dashes/underscores to spaces
    - Title case (first letter of each word capitalized)
    - Truncate at 100 chars at word boundary (add "..." if truncated)
    - Sanitize: strip non-printable unicode (control chars, RTL override)
    - Escape/reject pipe `|` chars (breaks registry table)

    Args:
        filename: Input filename (e.g., "my-video_file.mp4")

    Returns:
        Humanized title (e.g., "My Video File")

    Raises:
        ValueError: If filename contains pipe character
    """
    if "|" in filename:
        raise ValueError(f"Filename contains pipe character: {filename}")

    # Strip extension
    name = filename.rsplit(".", 1)[0]

    # Convert dashes/underscores to spaces
    name = re.sub(r"[-_]+", " ", name)

    # Title case
    name = name.title()

    # Sanitize: strip non-printable unicode (control chars, RTL override)
    name = "".join(
        c
        for c in name
        if unicodedata.category(c)[0] != "C"  # Exclude control characters
        and c not in ("\u202e", "\u202d")  # Exclude RTL/LTR override
    )

    # Truncate at 100 chars at word boundary
    if len(name) > 100:
        truncated = name[:100]
        # Find last space
        last_space = truncated.rfind(" ")
        if last_space > 0:
            name = truncated[:last_space] + "..."
        else:
            # No space found, truncate at 97 chars to fit "..."
            name = truncated[:97] + "..."

    return name.strip()


def format_timestamp(seconds: float) -> str:
    """Format seconds to [MM:SS] or [H:MM:SS] format.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"[{hours}:{minutes:02d}:{secs:02d}]"
    else:
        return f"[{minutes:02d}:{secs:02d}]"


def parse_srt(content: str) -> list[TranscriptSegment]:
    """Parse SRT subtitle format.

    SRT format:
    ```
    1
    00:00:00,000 --> 00:00:05,000
    First line of transcript

    2
    00:00:05,000 --> 00:00:10,000
    Second line of transcript
    ```

    Args:
        content: SRT file content

    Returns:
        List of TranscriptSegment objects

    Raises:
        ValueError: If SRT format is invalid
    """
    from .models import TranscriptSegment

    segments: list[TranscriptSegment] = []

    # Split by double newlines (entry separator)
    entries = re.split(r"\n\s*\n", content.strip())

    for entry in entries:
        if not entry.strip():
            continue

        lines = entry.strip().split("\n")
        if len(lines) < 3:
            continue

        # Skip index line (first line is usually a number)
        # Find the timestamp line
        timestamp_line = None
        text_start_idx = None

        for i, line in enumerate(lines):
            if "-->" in line:
                timestamp_line = line
                text_start_idx = i + 1
                break

        if timestamp_line is None or text_start_idx is None:
            continue

        # Parse timestamp
        try:
            time_parts = timestamp_line.split("-->")
            start_str = time_parts[0].strip()
            end_str = time_parts[1].strip()

            start = _parse_srt_timestamp(start_str)
            end = _parse_srt_timestamp(end_str)
        except (IndexError, ValueError):
            continue

        # Collect text lines
        text_lines = lines[text_start_idx:]
        text = " ".join(line.strip() for line in text_lines if line.strip())

        if text:
            segments.append(TranscriptSegment(start=start, end=end, text=text))

    return segments


def _parse_srt_timestamp(timestamp_str: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds.

    Args:
        timestamp_str: Timestamp string (e.g., "00:00:05,123")

    Returns:
        Time in seconds as float

    Raises:
        ValueError: If timestamp format is invalid
    """
    # Handle both comma and period as decimal separator
    timestamp_str = timestamp_str.replace(",", ".")

    parts = timestamp_str.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}") from e


def format_transcript_md(segments: list[TranscriptSegment], video_url: str, title: str) -> str:
    """Format transcript segments as markdown.

    Args:
        segments: List of TranscriptSegment objects
        video_url: YouTube video URL
        title: Video title

    Returns:
        Markdown-formatted transcript
    """
    lines = [f"# {title}", "", f"Video: {video_url}", "", "## Transcript", ""]

    for segment in segments:
        timestamp = format_timestamp(segment.start)
        lines.append(f"{timestamp} {segment.text}")

    return "\n".join(lines)
