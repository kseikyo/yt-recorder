"""Utility functions for yt-recorder."""

import platform
import shutil
from pathlib import Path


def safe_resolve(base: Path, untrusted: str) -> Path:
    """Resolve untrusted relative path, reject traversal and symlink escapes.

    Prevents path traversal by ensuring the resolved path stays within the
    base directory. Also rejects any path whose nominal location (or any
    ancestor between ``base`` and the leaf) is a symlink — symlinks pointing
    outside ``base`` would otherwise smuggle reads/writes onto arbitrary files
    even though the post-resolve check sees a path inside ``base``.

    Args:
        base: Base directory (trusted, must be absolute)
        untrusted: Relative path from user input/registry

    Returns:
        Resolved absolute path within base directory

    Raises:
        ValueError: If resolved path escapes base, is absolute, or any
            component is a symlink.
    """
    base_resolved = base.resolve()
    untrusted_path = Path(untrusted)

    if untrusted_path.is_absolute():
        raise ValueError(f"Path traversal rejected: absolute path not allowed: {untrusted}")

    # Pre-resolve: walk the nominal path component-by-component and refuse if
    # any segment is a symlink. We have to inspect the *unresolved* path so
    # that ``Path.resolve`` doesn't silently follow the link before we check.
    nominal = base_resolved / untrusted_path
    cursor = base_resolved
    for part in untrusted_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(
                f"Path traversal rejected: {untrusted} contains symlinked component: {cursor}"
            )

    resolved = nominal.resolve()

    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise ValueError(
            f"Path traversal rejected: {untrusted} escapes base directory {base_resolved}"
        ) from None

    return resolved


def find_chrome() -> str:
    """Find Chrome/Chromium executable path on the system.

    Searches for Chrome/Chromium in platform-specific locations:
    - macOS: /Applications/Google Chrome.app, /Applications/Chromium.app
    - Linux: google-chrome, google-chrome-stable, chromium-browser, chromium
    - Windows: Program Files and Program Files (x86)

    Returns:
        Path to Chrome/Chromium executable

    Raises:
        FileNotFoundError: If Chrome/Chromium not found with install instructions
    """
    system = platform.system().lower()
    candidates: list[str] = []

    if system == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "linux":
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    elif system == "windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

    for path in candidates:
        if Path(path).exists():
            return path

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Google Chrome.\n"
        "  macOS: brew install --cask google-chrome\n"
        "  Linux: apt install google-chrome-stable\n"
        "  Windows: https://google.com/chrome"
    )
