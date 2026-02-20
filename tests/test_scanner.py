from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from yt_recorder.adapters.scanner import ScanResult, scan_recordings


@pytest.fixture
def temp_recordings_dir() -> Generator[Path, None, None]:
    """Create a temporary recordings directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Create root-level files
        (base / "video1.mp4").touch()
        (base / "video2.mkv").touch()

        # Create subdirectories with files
        talks_dir = base / "talks"
        talks_dir.mkdir()
        (talks_dir / "talk1.mp4").touch()
        (talks_dir / "talk2.mp4").touch()

        ideas_dir = base / "ideas"
        ideas_dir.mkdir()
        (ideas_dir / "idea1.mp4").touch()

        # Create nested directory (depth > 1)
        nested = talks_dir / "nested"
        nested.mkdir()
        (nested / "deep.mp4").touch()

        # Create hidden files/dirs
        (base / ".hidden.mp4").touch()
        hidden_dir = base / ".hidden_dir"
        hidden_dir.mkdir()
        (hidden_dir / "file.mp4").touch()

        # Create symlink (target is hidden to avoid being scanned)
        symlink_target = base / ".symlink_target.mp4"
        symlink_target.touch()
        symlink = base / "symlink.mp4"
        symlink.symlink_to(symlink_target)

        # Create non-video files
        (base / "readme.txt").touch()
        (talks_dir / "notes.txt").touch()

        # Set mtimes for sorting test
        # Ensure deterministic ordering
        for i, file in enumerate(sorted(base.glob("**/*.mp4"))):
            os.utime(file, (1000 + i, 1000 + i))

        yield base


class TestScanRecordings:
    """Tests for scan_recordings function."""

    def test_scan_root_files_only(self, temp_recordings_dir: Path) -> None:
        """Test scanning root files with max_depth=0."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4", ".mkv"],
            exclude_dirs=[],
            max_depth=0,
        )

        # Should find video1.mp4 and video2.mkv at root
        assert len(results) == 2
        paths = {r.path.name for r in results}
        assert paths == {"video1.mp4", "video2.mkv"}

        # All should have playlist = directory name
        for result in results:
            assert result.playlist == temp_recordings_dir.name

    def test_scan_with_subdirs_depth_1(self, temp_recordings_dir: Path) -> None:
        """Test scanning with max_depth=1 includes subdirectory files."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4", ".mkv"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Should find: video1.mp4, video2.mkv (root) + talk1.mp4, talk2.mp4, idea1.mp4 (depth 1)
        # Should NOT find: deep.mp4 (depth 2)
        assert len(results) == 5

        # Check playlist names
        root_results = [
            r for r in results if r.path.parent.resolve() == temp_recordings_dir.resolve()
        ]
        assert len(root_results) == 2
        for r in root_results:
            assert r.playlist == temp_recordings_dir.name

        talks_results = [r for r in results if r.path.parent.name == "talks"]
        assert len(talks_results) == 2
        for r in talks_results:
            assert r.playlist == "talks"

        ideas_results = [r for r in results if r.path.parent.name == "ideas"]
        assert len(ideas_results) == 1
        for r in ideas_results:
            assert r.playlist == "ideas"

    def test_scan_excludes_hidden_files(self, temp_recordings_dir: Path) -> None:
        """Test that hidden files are excluded."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Should not find .hidden.mp4
        paths = {r.path.name for r in results}
        assert ".hidden.mp4" not in paths

    def test_scan_excludes_hidden_dirs(self, temp_recordings_dir: Path) -> None:
        """Test that hidden directories are excluded."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Should not find files in .hidden_dir
        paths = {r.path.name for r in results}
        assert "file.mp4" not in paths or all(r.path.parent.name != ".hidden_dir" for r in results)

    def test_scan_excludes_symlinks(self, temp_recordings_dir: Path) -> None:
        """Test that symlinks are excluded."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=0,
        )

        # Should not find symlink.mp4
        paths = {r.path.name for r in results}
        assert "symlink.mp4" not in paths

    def test_scan_respects_extension_filter(self, temp_recordings_dir: Path) -> None:
        """Test that only specified extensions are included."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=0,
        )

        # Should find only .mp4 files, not .mkv
        paths = {r.path.name for r in results}
        assert "video1.mp4" in paths
        assert "video2.mkv" not in paths

    def test_scan_excludes_non_video_files(self, temp_recordings_dir: Path) -> None:
        """Test that non-video files are excluded."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4", ".mkv"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Should not find .txt files
        paths = {r.path.name for r in results}
        assert "readme.txt" not in paths
        assert "notes.txt" not in paths

    def test_scan_respects_exclude_dirs(self, temp_recordings_dir: Path) -> None:
        """Test that excluded directories are skipped."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=["talks"],
            max_depth=1,
        )

        # Should find video1.mp4 (root) and idea1.mp4, but not talk1.mp4 or talk2.mp4
        assert len(results) == 2
        paths = {r.path.name for r in results}
        assert "video1.mp4" in paths
        assert "idea1.mp4" in paths
        assert "talk1.mp4" not in paths
        assert "talk2.mp4" not in paths

    def test_scan_respects_max_depth(self, temp_recordings_dir: Path) -> None:
        """Test that max_depth is respected."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Should not find deep.mp4 (at depth 2)
        paths = {r.path.name for r in results}
        assert "deep.mp4" not in paths

    def test_scan_sorted_by_mtime(self, temp_recordings_dir: Path) -> None:
        """Test that results are sorted by mtime ascending."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4", ".mkv"],
            exclude_dirs=[],
            max_depth=1,
        )

        # Verify sorted by mtime
        mtimes = [os.stat(r.path).st_mtime for r in results]
        assert mtimes == sorted(mtimes)

    def test_scan_returns_absolute_paths(self, temp_recordings_dir: Path) -> None:
        """Test that returned paths are absolute."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=0,
        )

        for result in results:
            assert result.path.is_absolute()

    def test_scan_empty_directory(self) -> None:
        """Test scanning an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            results = scan_recordings(
                directory=base,
                extensions=[".mp4"],
                exclude_dirs=[],
                max_depth=1,
            )

            assert results == []

    def test_scan_directory_with_no_matching_files(self, temp_recordings_dir: Path) -> None:
        """Test scanning with no matching extensions."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".avi"],
            exclude_dirs=[],
            max_depth=1,
        )

        assert results == []

    def test_scan_result_is_named_tuple(self, temp_recordings_dir: Path) -> None:
        """Test that ScanResult is a NamedTuple with correct fields."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=0,
        )

        assert len(results) > 0
        result = results[0]

        # Check it's a NamedTuple with correct fields
        assert isinstance(result, ScanResult)
        assert hasattr(result, "path")
        assert hasattr(result, "playlist")
        assert isinstance(result.path, Path)
        assert isinstance(result.playlist, str)

    def test_scan_case_insensitive_extensions(self, temp_recordings_dir: Path) -> None:
        """Test that extension matching is case-insensitive."""
        # Create uppercase extension file
        (temp_recordings_dir / "VIDEO.MP4").touch()

        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=[],
            max_depth=0,
        )

        # Should find both video1.mp4 and VIDEO.MP4
        paths = {r.path.name for r in results}
        assert "video1.mp4" in paths
        assert "VIDEO.MP4" in paths

    def test_scan_multiple_exclude_dirs(self, temp_recordings_dir: Path) -> None:
        """Test excluding multiple directories."""
        results = scan_recordings(
            directory=temp_recordings_dir,
            extensions=[".mp4"],
            exclude_dirs=["talks", "ideas"],
            max_depth=1,
        )

        # Should find only root video1.mp4
        assert len(results) == 1
        assert results[0].path.name == "video1.mp4"

    def test_scan_permission_error_handling(self) -> None:
        """Test graceful handling of permission errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            restricted_dir = base / "restricted"
            restricted_dir.mkdir()
            (restricted_dir / "file.mp4").touch()

            # Remove read permissions
            restricted_dir.chmod(0o000)

            try:
                results = scan_recordings(
                    directory=base,
                    extensions=[".mp4"],
                    exclude_dirs=[],
                    max_depth=1,
                )

                # Should handle gracefully and return empty or partial results
                assert isinstance(results, list)
            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)
