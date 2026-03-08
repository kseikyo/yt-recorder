from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from yt_recorder.domain.exceptions import SplitterError

logger = logging.getLogger(__name__)

TIER_1HR: float = 3300.0   # 55 minutes (buffer for 1-hour limit)
TIER_15MIN: float = 840.0  # 14 minutes (buffer for 15-minute limit)


class VideoSplitter:
    def get_duration(self, path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-of", "json",
                    "-show_format",
                    "-show_streams",
                    "-select_streams", "v:0",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise SplitterError("ffprobe not found. Install ffmpeg: brew install ffmpeg") from exc

        if result.returncode != 0:
            raise SplitterError(f"ffprobe failed for {path}: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise SplitterError(f"Cannot parse duration from ffprobe output: {result.stdout!r}") from exc

    def get_metadata(self, path: Path) -> dict[str, object]:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-of", "json",
                    "-show_format",
                    "-show_streams",
                    "-select_streams", "v:0",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise SplitterError("ffprobe not found. Install ffmpeg: brew install ffmpeg") from exc

        if result.returncode != 0:
            raise SplitterError(f"ffprobe failed for {path}: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            fmt = data["format"]
            streams = data.get("streams", [])
            return {
                "duration": float(fmt["duration"]),
                "size_bytes": int(fmt["size"]),
                "codec": streams[0].get("codec_name", "") if streams else "",
                "width": streams[0].get("width", 0) if streams else 0,
                "height": streams[0].get("height", 0) if streams else 0,
            }
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise SplitterError(f"Cannot parse metadata from ffprobe output: {result.stdout!r}") from exc

    def needs_split(self, path: Path, threshold_secs: float) -> bool:
        return self.get_duration(path) > threshold_secs

    def split(self, path: Path, threshold_secs: float) -> list[Path]:
        if not self.needs_split(path, threshold_secs):
            return [path]

        usage = shutil.disk_usage(path.parent)
        if usage.free < path.stat().st_size * 1.1:
            logger.warning("Low disk space: splitting %s may fail", path.name)

        temp_dir = path.parent / f".{path.stem}_parts"
        temp_dir.mkdir(exist_ok=True)

        output_pattern = temp_dir / f"{path.stem}_part%03d{path.suffix}"

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", str(path),
                    "-c", "copy",
                    "-map", "0",
                    "-segment_time", str(int(threshold_secs)),
                    "-f", "segment",
                    "-reset_timestamps", "1",
                    str(output_pattern),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise SplitterError("ffmpeg not found. Install: brew install ffmpeg") from exc

        if result.returncode != 0:
            for f in temp_dir.iterdir():
                f.unlink(missing_ok=True)
            raise SplitterError(f"ffmpeg failed: {result.stderr[-500:]}")

        parts = sorted(temp_dir.glob(f"{path.stem}_part*{path.suffix}"))

        if not parts:
            raise SplitterError(f"ffmpeg produced no output files in {temp_dir}")

        return parts

    def cleanup_parts(self, parts: list[Path]) -> None:
        for part in parts:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            parts[0].parent.rmdir()
        except (OSError, IndexError):
            pass
