from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from yt_recorder.domain.exceptions import SplitterError
from yt_recorder.log import log_context

logger = logging.getLogger(__name__)

TIER_1HR: float = 3300.0   # 55 minutes (buffer for 1-hour limit)
TIER_15MIN: float = 840.0  # 14 minutes (buffer for 15-minute limit)

# Epsilon (seconds) tolerating small mux drift when checking produced part durations
_PART_DURATION_EPSILON: float = 2.0

# Restrict characters used to build temp dir / part filenames from the source
# basename. The ffmpeg call uses list-form subprocess (no shell interpretation)
# so this is defense-in-depth, not a fix for an exploitable bug.
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")


def _slug(stem: str) -> str:
    slugged = _SLUG_RE.sub("_", stem)
    return slugged or "video"


def _compute_ffmpeg_timeout(duration_secs: float) -> float:
    # Re-encoding at -preset veryfast is typically faster than realtime but can
    # spike on slow disks or contested CPU. Allow ~4x realtime headroom + 60s baseline.
    return max(600.0, duration_secs * 4 + 60)


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
        source_duration = self.get_duration(path)
        if source_duration <= threshold_secs:
            return [path]

        with log_context(
            operation="split",
            filepath=str(path),
            threshold_secs=threshold_secs,
        ):
            usage = shutil.disk_usage(path.parent)
            if usage.free < path.stat().st_size * 1.1:
                logger.warning(
                    "low disk space: split may fail",
                    extra={"event": "split_low_disk"},
                )

            stem_slug = _slug(path.stem)
            temp_dir = path.parent / f".{stem_slug}_parts"
            temp_dir.mkdir(exist_ok=True)

            output_pattern = temp_dir / f"{stem_slug}_part%03d{path.suffix}"

            # Re-encode video (audio stream-copied) so ffmpeg can insert forced
            # keyframes at segment boundaries. Stream-copy cannot guarantee this
            # on screen recordings with sparse GOPs, which produced oversize parts
            # that YouTube rejected with "Processing abandoned".
            seg = int(threshold_secs)
            estimated_parts = max(
                1, int(source_duration // seg) + (1 if source_duration % seg else 0)
            )
            timeout_secs = _compute_ffmpeg_timeout(source_duration)
            logger.info(
                "splitting video (re-encode with libx264 veryfast crf23, may take several minutes)",
                extra={
                    "event": "split_start",
                    "duration_secs": source_duration,
                    "estimated_parts": estimated_parts,
                    "timeout_secs": timeout_secs,
                },
            )
            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-i", str(path),
                        "-map", "0",
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "23",
                        "-force_key_frames", f"expr:gte(t,n_forced*{seg})",
                        "-c:a", "copy",
                        "-f", "segment",
                        "-segment_time", str(seg),
                        "-reset_timestamps", "1",
                        str(output_pattern),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_secs,
                )
            except FileNotFoundError as exc:
                raise SplitterError("ffmpeg not found. Install: brew install ffmpeg") from exc

            if result.returncode != 0:
                for f in temp_dir.iterdir():
                    f.unlink(missing_ok=True)
                logger.error(
                    "ffmpeg split failed",
                    extra={
                        "event": "split_failed",
                        "returncode": result.returncode,
                        "stderr_tail": result.stderr[-500:],
                    },
                )
                raise SplitterError(f"ffmpeg failed: {result.stderr[-500:]}")

            parts = sorted(temp_dir.glob(f"{stem_slug}_part*{path.suffix}"))

            if not parts:
                raise SplitterError(f"ffmpeg produced no output files in {temp_dir}")

            logger.info(
                "split produced parts",
                extra={
                    "event": "split_done",
                    "part_count": len(parts),
                    "parts": [p.name for p in parts],
                },
            )

            for part in parts:
                part_duration = self.get_duration(part)
                if part_duration > threshold_secs + _PART_DURATION_EPSILON:
                    self.cleanup_parts(parts)
                    raise SplitterError(
                        f"split produced oversize part {part.name}: "
                        f"{part_duration:.1f}s > threshold {threshold_secs:.1f}s"
                    )

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
