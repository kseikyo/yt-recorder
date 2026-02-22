"""Utility functions for yt-recorder."""

import platform
import shutil
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
        raise ValueError(f"Path traversal rejected: absolute path not allowed: {untrusted}")

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
