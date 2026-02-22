"""Tests for utility functions."""

import tempfile
from pathlib import Path

import pytest

from yt_recorder.utils import safe_resolve


class TestSafeResolve:
    """Test safe_resolve path traversal protection."""

    def test_normal_relative_path(self) -> None:
        """Normal relative path within base directory succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            (base / "subdir").mkdir()
            (base / "subdir" / "file.mp4").touch()

            result = safe_resolve(base, "subdir/file.mp4")
            assert result == base / "subdir" / "file.mp4"
            assert result.is_relative_to(base)

    def test_dotdot_traversal_rejected(self) -> None:
        """Dotdot traversal (../../etc/passwd) raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with pytest.raises(ValueError, match="Path traversal rejected"):
                safe_resolve(base, "../../etc/passwd")

    def test_absolute_path_rejected(self) -> None:
        """Absolute path in untrusted input raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with pytest.raises(ValueError, match="absolute path not allowed"):
                safe_resolve(base, "/etc/passwd")

    def test_symlink_escape_rejected(self) -> None:
        """Symlink pointing outside base directory raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            outside = Path(tmpdir).parent / "outside_file"
            outside.touch()

            symlink = base / "link_to_outside"
            symlink.symlink_to(outside)

            with pytest.raises(ValueError, match="Path traversal rejected"):
                safe_resolve(base, "link_to_outside")

            outside.unlink()
