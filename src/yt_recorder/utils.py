"""Utility functions for yt-recorder."""

from pathlib import Path


def safe_resolve(base: Path, untrusted: str) -> Path:
    """Resolve untrusted relative path, reject traversal attacks.

    Prevents path traversal vulnerabilities by ensuring the resolved path
    stays within the base directory. Rejects absolute paths and dotdot
    traversal attempts.

    Args:
        base: Base directory (trusted, must be absolute)
        untrusted: Relative path from user input/registry

    Returns:
        Resolved absolute path within base directory

    Raises:
        ValueError: If resolved path escapes base directory or is absolute
    """
    # Resolve both paths to absolute form
    base_resolved = base.resolve()
    untrusted_path = Path(untrusted)

    # Reject absolute paths in untrusted input
    if untrusted_path.is_absolute():
        raise ValueError(
            f"Path traversal rejected: absolute path not allowed: {untrusted}"
        )

    # Resolve the untrusted path relative to base
    resolved = (base_resolved / untrusted_path).resolve()

    # Verify resolved path is within base directory
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise ValueError(
            f"Path traversal rejected: {untrusted} escapes base directory {base_resolved}"
        )

    return resolved
