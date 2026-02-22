from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from yt_recorder.domain.exceptions import (
    RegistryFileNotFoundError,
    RegistryParseError,
    RegistryWriteError,
)
from yt_recorder.domain.models import RegistryEntry


class MarkdownRegistryStore:
    """Markdown-based registry store with dynamic account columns.

    Stores video metadata in a markdown table format with dynamic columns
    for each configured account. Supports atomic writes for crash safety.
    """

    def __init__(self, registry_path: Path, account_names: list[str]) -> None:
        """Initialize registry store.

        Args:
            registry_path: Path to registry.md file
            account_names: List of account names (e.g., ["primary", "mirror-1"])
        """
        self.registry_path = registry_path
        self.account_names = account_names

    def load(self) -> list[RegistryEntry]:
        """Load all entries from registry.

        Returns:
            List of RegistryEntry objects

        Raises:
            RegistryFileNotFoundError: If registry file doesn't exist
            RegistryParseError: If registry file is malformed
        """
        if not self.registry_path.exists():
            raise RegistryFileNotFoundError(f"Registry file not found: {self.registry_path}")

        try:
            content = self.registry_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise RegistryParseError(f"Failed to read registry: {e}") from e

        entries: list[RegistryEntry] = []
        lines = content.strip().split("\n")

        header_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("|") and "File" in line:
                header_idx = i
                break

        if header_idx is None or header_idx + 1 >= len(lines):
            return entries

        headers = self._parse_header(lines[header_idx])
        if not headers:
            raise RegistryParseError("Invalid registry header format")

        for line in lines[header_idx + 2 :]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            try:
                entry = self._parse_row(line, headers)
                if entry:
                    entries.append(entry)
            except (ValueError, IndexError) as e:
                raise RegistryParseError(f"Failed to parse row: {line}") from e

        return entries

    def append(self, entry: RegistryEntry) -> None:
        """Append a new entry to registry.

        Creates registry file if it doesn't exist. Uses atomic write
        (temp file + os.replace) for crash safety.

        Args:
            entry: RegistryEntry to append

        Raises:
            RegistryWriteError: If write fails
        """
        try:
            if not self.registry_path.exists():
                self._create_registry()

            content = self.registry_path.read_text(encoding="utf-8")
            new_row = self._format_row(entry)
            new_content = content.rstrip() + "\n" + new_row + "\n"

            self._atomic_write(new_content)
        except (OSError, UnicodeDecodeError) as e:
            raise RegistryWriteError(f"Failed to append entry: {e}") from e

    def update_transcript(self, file: str, status: bool) -> None:
        """Update transcript status for a file.

        Args:
            file: Relative file path
            status: True if transcript available, False otherwise

        Raises:
            RegistryWriteError: If update fails
        """
        try:
            entries = self.load()
            updated = False

            for i, entry in enumerate(entries):
                if entry.file == file:
                    entries[i] = RegistryEntry(
                        file=entry.file,
                        playlist=entry.playlist,
                        uploaded_date=entry.uploaded_date,
                        has_transcript=status,
                        account_ids=entry.account_ids,
                    )
                    updated = True
                    break

            if not updated:
                raise RegistryWriteError(f"File not found in registry: {file}")

            self._write_all(entries)
        except RegistryWriteError:
            raise
        except Exception as e:
            raise RegistryWriteError(f"Failed to update transcript: {e}") from e

    def update_account_id(self, file: str, account: str, video_id: str) -> None:
        """Update a single account's video ID for a registry entry.

        Args:
            file: Relative file path
            account: Account name to update
            video_id: New video ID

        Raises:
            RegistryWriteError: If update fails or file not found
        """
        entries = self.load()
        for i, entry in enumerate(entries):
            if entry.file == file:
                new_ids = dict(entry.account_ids)
                new_ids[account] = video_id
                entries[i] = RegistryEntry(
                    file=entry.file,
                    playlist=entry.playlist,
                    uploaded_date=entry.uploaded_date,
                    has_transcript=entry.has_transcript,
                    account_ids=new_ids,
                )
                self._write_all(entries)
                return
        raise RegistryWriteError(f"File not found in registry: {file}")

    def is_registered(self, relative_path: str) -> bool:
        """Check if file is registered.

        Args:
            relative_path: Relative path from recordings directory

        Returns:
            True if file is in registry, False otherwise
        """
        try:
            entries = self.load()
            return any(entry.file == relative_path for entry in entries)
        except RegistryFileNotFoundError:
            return False

    def get_video_id(self, file: str, account: str) -> str | None:
        """Get video ID for a file on a specific account.

        Args:
            file: Relative file path
            account: Account name

        Returns:
            Video ID if available, None otherwise
        """
        try:
            entries = self.load()
            for entry in entries:
                if entry.file == file:
                    video_id = entry.account_ids.get(account)
                    if video_id and video_id != "—":
                        return video_id
                    return None
            return None
        except RegistryFileNotFoundError:
            return None

    def _create_registry(self) -> None:
        """Create empty registry file with header."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        header = "# Recordings Registry\n\n"
        table_header = self._format_table_header()
        separator = self._format_separator()

        content = header + table_header + "\n" + separator + "\n"
        self._atomic_write(content)

    def _format_table_header(self) -> str:
        """Format markdown table header."""
        columns = [
            "File",
            "Playlist",
            "Uploaded",
            "Transcript",
            *self.account_names,
        ]
        return "| " + " | ".join(columns) + " |"

    def _format_separator(self) -> str:
        """Format markdown table separator."""
        columns = [
            "File",
            "Playlist",
            "Uploaded",
            "Transcript",
            *self.account_names,
        ]
        return "| " + " | ".join(["---"] * len(columns)) + " |"

    def _format_row(self, entry: RegistryEntry) -> str:
        """Format registry entry as markdown table row."""
        transcript_mark = "✅" if entry.has_transcript else "❌"
        account_values = [entry.account_ids.get(name, "—") for name in self.account_names]

        values = [
            entry.file,
            entry.playlist,
            entry.uploaded_date.isoformat(),
            transcript_mark,
            *account_values,
        ]

        return "| " + " | ".join(values) + " |"

    def _parse_header(self, line: str) -> list[str] | None:
        """Parse markdown table header line."""
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]

        if len(parts) < 4:
            return None

        return parts

    def _parse_row(self, line: str, headers: list[str]) -> RegistryEntry | None:
        """Parse markdown table row into RegistryEntry."""
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]

        if len(parts) < 4:
            return None

        file_path = parts[0]
        playlist = parts[1]
        uploaded_str = parts[2]
        transcript_mark = parts[3]

        try:
            uploaded_date = date.fromisoformat(uploaded_str)
        except ValueError as e:
            raise ValueError(f"Invalid date format: {uploaded_str}") from e

        has_transcript = transcript_mark == "✅"

        account_ids: dict[str, str] = {}
        for i, account_name in enumerate(self.account_names):
            idx = 4 + i
            account_ids[account_name] = parts[idx] if idx < len(parts) else "—"

        return RegistryEntry(
            file=file_path,
            playlist=playlist,
            uploaded_date=uploaded_date,
            has_transcript=has_transcript,
            account_ids=account_ids,
        )

    def _write_all(self, entries: list[RegistryEntry]) -> None:
        """Write all entries to registry (overwrites existing)."""
        header = "# Recordings Registry\n\n"
        table_header = self._format_table_header()
        separator = self._format_separator()

        lines = [header, table_header, separator]
        for entry in entries:
            lines.append(self._format_row(entry))

        content = "\n".join(lines) + "\n"
        self._atomic_write(content)

    def _atomic_write(self, content: str) -> None:
        """Write content atomically using temp file + os.replace."""
        try:
            fd, temp_path = tempfile.mkstemp(dir=self.registry_path.parent, text=True)
            try:
                os.chmod(temp_path, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(temp_path, self.registry_path)
            except Exception:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            raise RegistryWriteError(f"Atomic write failed: {e}") from e
