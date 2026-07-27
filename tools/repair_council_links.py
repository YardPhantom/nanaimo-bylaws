#!/usr/bin/env python3
"""Repair legacy local Council links that incorrectly retain .ashx/.aspx suffixes.

The City/eSCRIBE handler suffix belongs to the remote source URL. Locally archived
copies must be ordinary .pdf files. This utility renames any legacy local PDF
whose filename ends in .ashx/.aspx and updates the Council JSON datasets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = (
    ROOT / "data" / "council-documents.json",
    ROOT / "data" / "council-items.json",
    ROOT / "data" / "council-discussions.json",
)
LEGACY_SUFFIXES = {".ashx", ".aspx"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def is_remote(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def repair_local_path(value: Any) -> tuple[Any, bool, bool]:
    """Return (new value, changed, missing).

    Missing means a legacy-looking local path had no usable local PDF. Callers
    should clear that local field and fall back to the official source URL.
    """
    if not isinstance(value, str) or not value.strip() or is_remote(value):
        return value, False, False

    normalized = value.replace("\\", "/").lstrip("/")
    local = ROOT / normalized
    if local.suffix.lower() not in LEGACY_SUFFIXES:
        return normalized, normalized != value, False

    target = local.with_suffix(".pdf")
    if local.exists():
        try:
            header = local.read_bytes()[:5]
        except OSError:
            header = b""
        if header == b"%PDF-":
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                local.replace(target)
            else:
                local.unlink()

    if target.exists():
        return target.relative_to(ROOT).as_posix(), True, False
    return None, True, True


def walk(value: Any, stats: dict[str, int]) -> Any:
    if isinstance(value, list):
        return [walk(item, stats) for item in value]
    if not isinstance(value, dict):
        return value

    result = dict(value)
    for key in ("local_path", "archive_path", "local_document"):
        if key not in result:
            continue
        repaired, changed, missing = repair_local_path(result.get(key))
        if changed:
            stats["updated_links"] += 1
        if missing:
            stats["missing_local_files"] += 1
        result[key] = repaired

    # Homepage discussions can contain a local path in the generic url field.
    url = result.get("url")
    if isinstance(url, str) and not is_remote(url):
        repaired, changed, missing = repair_local_path(url)
        if changed:
            stats["updated_links"] += 1
        if missing:
            stats["missing_local_files"] += 1
            repaired = result.get("source_document_url") or result.get("meeting_url") or "#"
        result["url"] = repaired

    return {key: walk(item, stats) for key, item in result.items()}


def main() -> int:
    stats = {"updated_links": 0, "missing_local_files": 0, "files_updated": 0}
    for path in DATA_FILES:
        if not path.exists():
            print(f"Skipped missing {path.relative_to(ROOT)}")
            continue
        payload = read_json(path)
        repaired = walk(payload, stats)
        write_json(path, repaired)
        stats["files_updated"] += 1
        print(f"Repaired {path.relative_to(ROOT)}")

    print(
        "Council link repair complete: "
        f"{stats['updated_links']} links updated, "
        f"{stats['missing_local_files']} missing legacy files cleared, "
        f"{stats['files_updated']} datasets written."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
