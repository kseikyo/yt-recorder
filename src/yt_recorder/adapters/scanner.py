from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple


class ScanResult(NamedTuple):
    """Result of scanning a recording file.

    Attributes:
        path: Absolute path to the video file
        playlist: Playlist name derived from folder structure
    """

    path: Path
    playlist: str


def scan_recordings(
    directory: Path,
    extensions: list[str],
    exclude_dirs: list[str],
    max_depth: int,
) -> list[ScanResult]:
    """Scan recordings directory and return (path, playlist_name) tuples.

    Folder→Playlist Mapping:
    - Root files → playlist = directory name
    - Depth=1 files → playlist = subdirectory name
    - Depth > max_depth → excluded

    Args:
        directory: Root directory to scan
        extensions: List of file extensions to include (e.g., [".mp4", ".mkv"])
        exclude_dirs: List of directory names to exclude (e.g., ["transcripts"])
        max_depth: Maximum recursion depth (0 = root only, 1 = root + 1 level)

    Returns:
        List of (absolute_path, playlist_name) tuples sorted by mtime ascending

    Exclusions:
        - Hidden files/dirs (starting with .)
        - Configured exclude_dirs
        - Symlinks
        - Files with non-matching extensions
        - Files at depth > max_depth
    """
    results: list[ScanResult] = []
    dir_name = directory.name

    def _scan_recursive(current_dir: Path, current_depth: int) -> None:
        """Recursively scan directory up to max_depth."""
        if current_depth > max_depth:
            return

        try:
            entries = sorted(current_dir.iterdir())
        except (OSError, PermissionError):
            return

        for entry in entries:
            # Skip hidden files/dirs
            if entry.name.startswith("."):
                continue

            # Skip symlinks
            if entry.is_symlink():
                continue

            if entry.is_dir():
                # Skip excluded directories
                if entry.name in exclude_dirs:
                    continue

                # Recurse into subdirectory
                _scan_recursive(entry, current_depth + 1)

            elif entry.is_file():
                # Check extension
                if entry.suffix.lower() not in extensions:
                    continue

                # Determine playlist name based on depth
                if current_depth == 0:
                    # Root level file → playlist = directory name
                    playlist = dir_name
                else:
                    # Depth 1+ file → playlist = immediate parent directory name
                    playlist = current_dir.name

                results.append(ScanResult(path=entry.resolve(), playlist=playlist))

    _scan_recursive(directory, 0)

    # Sort by mtime ascending
    def get_mtime(r: ScanResult) -> float:
        try:
            return os.stat(r.path).st_mtime
        except FileNotFoundError:
            return 0.0

    results.sort(key=get_mtime)

    return results
