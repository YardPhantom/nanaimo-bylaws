#!/usr/bin/env python3
"""Shared content-addressed PDF archive helpers.

The collectors keep their historical timestamped folder layout, but this module
prevents a PDF with an already-known SHA-256 hash from being written to the
archive a second time. Existing archive files are preferred over network
requests and can be copied back to a missing live location.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import os
import shutil


@dataclass(frozen=True)
class ArchiveStoreResult:
    path: Path
    sha256: str
    created: bool


def sha256_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_url(value: str | None) -> str:
    """Normalize a source URL while removing known presentation-only fields."""
    if not value:
        return ""
    parsed = urlparse(value.strip())
    query = urlencode(sorted(
        (
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in {"fillwidth", "_"}
        ),
        key=lambda pair: (pair[0].lower(), pair[1]),
    ))
    path = parsed.path or "/"
    path = "/".join(part for part in path.split("/") if part)
    path = f"/{path}" if path else "/"
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path.rstrip("/") or "/",
        "",
        query,
        "",
    ))


def existing_path(root: Path, value: str | Path | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate if candidate.is_file() else None


def copy_if_needed(source: Path, destination: Path) -> bool:
    """Copy source only when destination is missing or has different content."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            if source.stat().st_size == destination.stat().st_size and sha256_file(source) == sha256_file(destination):
                return False
        except OSError:
            pass
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return True


def source_headers(headers: Mapping[str, Any] | None, final_url: str | None = None) -> dict[str, Any]:
    headers = headers or {}
    length = headers.get("Content-Length") or headers.get("content-length")
    try:
        parsed_length: int | None = int(length) if length not in (None, "") else None
    except (TypeError, ValueError):
        parsed_length = None
    return {
        "source_etag": headers.get("ETag") or headers.get("etag"),
        "source_last_modified": headers.get("Last-Modified") or headers.get("last-modified"),
        "source_content_length": parsed_length,
        "source_content_type": headers.get("Content-Type") or headers.get("content-type"),
        "source_final_url": final_url,
    }


def remote_state_changed(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    local_size: int | None = None,
) -> bool:
    """Return True only when a meaningful remote validator actually changed.

    Missing validators never force a PDF download. This is intentional: an
    already archived PDF is reused unless the server supplies evidence that the
    source changed, or the collector discovers a new source URL.
    """
    if not previous or not current:
        return False

    previous_final = canonical_url(str(previous.get("source_final_url") or ""))
    current_final = canonical_url(str(current.get("source_final_url") or ""))
    if previous_final and current_final and previous_final != current_final:
        return True

    for key in ("source_etag", "source_last_modified"):
        before = previous.get(key)
        after = current.get(key)
        if before and after and str(before).strip() != str(after).strip():
            return True

    before_length = previous.get("source_content_length")
    after_length = current.get("source_content_length")
    if after_length not in (None, ""):
        try:
            after_length_int = int(after_length)
            if before_length not in (None, "") and int(before_length) != after_length_int:
                return True

            # Older records may not have stored HTTP validators. For original
            # PDFs, a different HEAD Content-Length is still evidence that the
            # remote file changed, without downloading its body.
            current_type = str(current.get("source_content_type") or "").lower()
            if before_length in (None, "") and local_size is not None and "pdf" in current_type:
                if int(local_size) != after_length_int:
                    return True
        except (TypeError, ValueError):
            pass
    return False


class PdfArchiveIndex:
    """Hash index for every PDF already held under the archive root."""

    def __init__(self, archive_root: Path):
        self.archive_root = archive_root
        self.by_hash: dict[str, Path] = {}
        self.by_name: dict[str, list[Path]] = {}
        self.duplicates: dict[str, list[Path]] = {}
        self._scan()

    def _scan(self) -> None:
        if not self.archive_root.exists():
            return
        for path in sorted(self.archive_root.rglob("*.pdf")):
            if not path.is_file():
                continue
            try:
                digest = sha256_file(path)
            except OSError:
                continue
            self.by_name.setdefault(path.name.lower(), []).append(path)
            current = self.by_hash.get(digest)
            if current is None:
                self.by_hash[digest] = path
            else:
                self.duplicates.setdefault(digest, [current]).append(path)

    @property
    def duplicate_file_count(self) -> int:
        return sum(max(0, len(paths) - 1) for paths in self.duplicates.values())

    def canonical_for_file(self, path: Path) -> tuple[str, Path | None]:
        digest = sha256_file(path)
        return digest, self.by_hash.get(digest)

    def find_first(self, candidates: Iterable[Path | None]) -> Path | None:
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        return None

    def store_bytes(self, content: bytes, desired_path: Path) -> ArchiveStoreResult:
        digest = sha256_bytes(content)
        existing = self.by_hash.get(digest)
        if existing and existing.is_file():
            return ArchiveStoreResult(existing, digest, False)

        target = self._available_target(desired_path, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
        self.by_hash[digest] = target
        self.by_name.setdefault(target.name.lower(), []).append(target)
        return ArchiveStoreResult(target, digest, True)

    def ensure_file(self, source: Path, desired_path: Path) -> ArchiveStoreResult:
        digest = sha256_file(source)
        existing = self.by_hash.get(digest)
        if existing and existing.is_file():
            return ArchiveStoreResult(existing, digest, False)

        target = self._available_target(desired_path, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
        self.by_hash[digest] = target
        self.by_name.setdefault(target.name.lower(), []).append(target)
        return ArchiveStoreResult(target, digest, True)

    @staticmethod
    def _available_target(desired_path: Path, digest: str) -> Path:
        if not desired_path.exists():
            return desired_path
        try:
            if sha256_file(desired_path) == digest:
                return desired_path
        except OSError:
            pass
        return desired_path.with_name(f"{desired_path.stem}-{digest[:10]}{desired_path.suffix}")
