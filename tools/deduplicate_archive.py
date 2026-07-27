#!/usr/bin/env python3
"""Consolidate duplicate archive PDFs by SHA-256 without breaking JSON links.

By default this command reports duplicates. Use ``--apply`` to rewrite exact
archive-path references in runtime/archive JSON, merge text sidecars, and
remove redundant PDF copies. The oldest lexicographic archive path is retained
as the canonical copy.
"""
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any
import json
import os
import shutil

from archive_cache import sha256_file

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive"
JSON_ROOTS = (ROOT / "data", ARCHIVE)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def duplicate_groups() -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    if not ARCHIVE.exists():
        return groups
    for path in sorted(ARCHIVE.rglob("*.pdf")):
        if not path.is_file():
            continue
        try:
            digest = sha256_file(path)
        except OSError as exc:
            print(f"Skipped unreadable PDF {path}: {exc}")
            continue
        groups.setdefault(digest, []).append(path)
    return {digest: paths for digest, paths in groups.items() if len(paths) > 1}


def replace_values(value: Any, replacements: dict[str, str]) -> tuple[Any, int]:
    if isinstance(value, dict):
        changed = 0
        output = {}
        for key, item in value.items():
            replacement, count = replace_values(item, replacements)
            output[key] = replacement
            changed += count
        return output, changed
    if isinstance(value, list):
        changed = 0
        output = []
        for item in value:
            replacement, count = replace_values(item, replacements)
            output.append(replacement)
            changed += count
        return output, changed
    if isinstance(value, str):
        replacement = replacements.get(value)
        if replacement is None:
            replacement = replacements.get(value.replace("\\", "/"))
        return (replacement, 1) if replacement is not None and replacement != value else (value, 0)
    return value, 0


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def merge_sidecars(canonical: Path, duplicate: Path) -> None:
    canonical_text = canonical.with_suffix(".txt")
    duplicate_text = duplicate.with_suffix(".txt")
    if duplicate_text.is_file():
        duplicate_value = duplicate_text.read_text(encoding="utf-8", errors="replace")
        canonical_value = (
            canonical_text.read_text(encoding="utf-8", errors="replace")
            if canonical_text.is_file() else ""
        )
        if len(duplicate_value.strip()) > len(canonical_value.strip()):
            canonical_text.parent.mkdir(parents=True, exist_ok=True)
            canonical_text.write_text(duplicate_value, encoding="utf-8")

    canonical_source = canonical.with_suffix(".source.html")
    duplicate_source = duplicate.with_suffix(".source.html")
    if duplicate_source.is_file() and not canonical_source.is_file():
        canonical_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(duplicate_source, canonical_source)


def json_files() -> list[Path]:
    files: set[Path] = set()
    for root in JSON_ROOTS:
        if root.exists():
            files.update(path for path in root.rglob("*.json") if path.is_file())
    return sorted(files)


def apply_deduplication(groups: dict[str, list[Path]]) -> tuple[int, int, int]:
    replacements: dict[str, str] = {}
    duplicate_paths: list[tuple[Path, Path]] = []

    for paths in groups.values():
        canonical = sorted(paths)[0]
        canonical_pdf = relative(canonical)
        canonical_text = relative(canonical.with_suffix(".txt"))
        canonical_source = relative(canonical.with_suffix(".source.html"))
        for duplicate in sorted(paths)[1:]:
            replacements[relative(duplicate)] = canonical_pdf
            replacements[relative(duplicate.with_suffix(".txt"))] = canonical_text
            replacements[relative(duplicate.with_suffix(".source.html"))] = canonical_source
            duplicate_paths.append((canonical, duplicate))

    parsed_files: list[tuple[Path, Any]] = []
    parse_failures: list[Path] = []
    for path in json_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parse_failures.append(path)
            continue
        parsed_files.append((path, payload))

    if parse_failures:
        message = "Archive deduplication aborted because JSON files could not be parsed:\n" + "\n".join(
            f"  {path}" for path in parse_failures
        )
        raise RuntimeError(message)

    rewritten_files = 0
    rewritten_values = 0
    for path, payload in parsed_files:
        updated, changes = replace_values(payload, replacements)
        if changes:
            write_json(path, updated)
            rewritten_files += 1
            rewritten_values += changes

    removed = 0
    for canonical, duplicate in duplicate_paths:
        merge_sidecars(canonical, duplicate)
        duplicate.unlink(missing_ok=True)
        duplicate.with_suffix(".txt").unlink(missing_ok=True)
        duplicate.with_suffix(".source.html").unlink(missing_ok=True)
        removed += 1

    return removed, rewritten_files, rewritten_values


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Rewrite JSON references and remove redundant PDF copies.")
    parser.add_argument("--check", action="store_true", help="Return a failure code when duplicate archive PDFs remain.")
    args = parser.parse_args()

    groups = duplicate_groups()
    duplicate_count = sum(len(paths) - 1 for paths in groups.values())
    if not duplicate_count:
        print("Archive PDF check passed: no duplicate SHA-256 content found.")
        return 0

    print(f"Detected {duplicate_count} duplicate archive PDFs across {len(groups)} content hashes.")
    for digest, paths in sorted(groups.items()):
        print(f"  {digest[:12]}: keep {relative(sorted(paths)[0])}; remove {len(paths) - 1} duplicate(s)")

    if args.apply:
        try:
            removed, rewritten_files, rewritten_values = apply_deduplication(groups)
        except RuntimeError as exc:
            print(exc)
            return 1
        remaining = duplicate_groups()
        remaining_count = sum(len(paths) - 1 for paths in remaining.values())
        print(f"Removed {removed} duplicate PDFs; rewrote {rewritten_values} path references in {rewritten_files} JSON files.")
        if remaining_count:
            print(f"Archive deduplication incomplete: {remaining_count} duplicate PDFs remain.")
            return 1
        print("Archive deduplication complete.")
        return 0

    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
