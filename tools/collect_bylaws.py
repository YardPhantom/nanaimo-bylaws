#!/usr/bin/env python3
"""Collect and archive the City of Nanaimo public bylaw index.

Usage:
  python tools/collect_bylaws.py
  python tools/collect_bylaws.py --download-pdfs

Every run keeps the live dataset at ``data/bylaws.json`` and writes a
Vancouver-time snapshot under ``archive/YYYY-MM-DD/HHMMSS/``. The new dataset
is compared with the most recent earlier snapshot and the results are written
to both the snapshot and ``data/change-log.json``.

Dependencies: requests, beautifulsoup4
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import argparse
import json
import re
import sys
import time
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from pdf_text import extract_pdf_text
from archive_cache import (
    PdfArchiveIndex,
    canonical_url,
    copy_if_needed,
    existing_path,
    remote_state_changed,
    source_headers,
)
from bylaw_relationships import infer_relationships, build_relationship_graph

ROOT = Path(__file__).resolve().parents[1]
INDEX = "https://www.nanaimo.ca/bylaws/All"
OUT = ROOT / "data" / "bylaws.json"
CHANGE_LOG = ROOT / "data" / "change-log.json"
SUMMARY = ROOT / "data" / "bylaws-summary.json"
RELATIONSHIPS = ROOT / "data" / "bylaw-relationships.json"
HOMEPAGE = ROOT / "index.html"
CURRENT_PDF_DIR = ROOT / "bylaws" / "pdf"
ARCHIVE_DIR = ROOT / "archive"
TZ = ZoneInfo("America/Vancouver")
COMPARE_FIELDS = (
    "title",
    "description",
    "year",
    "category",
    "status",
    "official_pdf",
    "source",
    "legal_status",
    "relationships",
)



def normalize_category_name(value):
    """Map retired category labels to their current public label."""
    return "Transportation" if str(value or "").strip() == "Transportation & Parking" else str(value or "").strip()

def now_local() -> datetime:
    return datetime.now(TZ)


def number_from(text: str, href: str) -> str | None:
    match = re.search(r"(?:NO\.?\s*|ViewBylaw/)(\d{3,4}(?:\.\d+)*)(?:\.pdf)?", f"{text} {href}", re.I)
    return match.group(1) if match else None


def category(text: str) -> str:
    source = text.lower()
    groups = {
        "Land Use & Zoning": ["zoning", "development", "building", "city plan"],
        "Transportation": ["traffic", "highway", "parking", "vehicle"],
        "Public Safety": ["fire", "alarm", "firearm", "firework", "flood"],
        "Animals": ["animal"],
        "Business & Licensing": ["business", "licence", "accommodation"],
        "Environment": ["climate", "waste", "water", "dust"],
        "Parks & Recreation": ["park", "recreation", "cemetery"],
        "Administration & Governance": [
            "council", "election", "ethics", "conduct", "procedure", "privacy"
        ],
        "Finance": ["financial", "fund", "fees", "charge", "tax", "borrowing"],
    }
    for group, words in groups.items():
        if any(word in source for word in words):
            return group
    return "Other"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def previous_snapshot(current_snapshot: Path) -> Path | None:
    candidates = sorted(
        path for path in ARCHIVE_DIR.glob("*/*/bylaws.json")
        if path.parent != current_snapshot
    )
    return candidates[-1] if candidates else None


def compare_records(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    old = {str(item.get("number")): item for item in previous if item.get("number")}
    new = {str(item.get("number")): item for item in current if item.get("number")}

    added = [new[number] for number in sorted(new.keys() - old.keys())]
    removed = [old[number] for number in sorted(old.keys() - new.keys())]
    changed: list[dict[str, Any]] = []

    for number in sorted(old.keys() & new.keys()):
        differences = {}
        for field in COMPARE_FIELDS:
            before = old[number].get(field)
            after = new[number].get(field)
            if before != after:
                differences[field] = {"before": before, "after": after}
        if differences:
            changed.append({
                "number": number,
                "title": new[number].get("title") or old[number].get("title"),
                "fields": differences,
            })

    return {
        "summary": {
            "added": len(added),
            "changed": len(changed),
            "removed": len(removed),
        },
        "added": added,
        "changed": changed,
        "removed": removed,
    }



def classify_change_event(
    change_type: str,
    record: dict[str, Any],
    differences: dict[str, Any] | None = None,
) -> str:
    """Return the user-facing change status for a collected record event."""
    if change_type == "added":
        return "New"
    if change_type == "removed":
        return "Repealed"

    differences = differences or {}
    after_status = str(
        differences.get("legal_status", {}).get("after")
        or record.get("legal_status")
        or ""
    ).lower()
    relationship_after = differences.get("relationships", {}).get("after") or {}
    searchable = " ".join([
        after_status,
        str(record.get("title") or ""),
        str(record.get("description") or ""),
        json.dumps(relationship_after, ensure_ascii=False),
    ]).lower()

    if "repeal" in searchable or "replaced" in searchable:
        return "Repealed"
    if "consolidat" in searchable:
        return "Consolidated"
    return "Amended"


def build_change_events(
    comparison: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    """Convert one snapshot comparison into chronological homepage events."""
    events: list[dict[str, Any]] = []

    for record in comparison.get("added", []):
        number = str(record.get("number") or "")
        events.append({
            "id": f"{generated_at}:added:{number}",
            "date": generated_at,
            "change_type": "added",
            "status": classify_change_event("added", record),
            "number": number,
            "title": record.get("title") or f"Bylaw {number}",
            "category": record.get("category") or "Other",
            "year": record.get("year"),
            "detail_url": record.get("detail_url") or f"detail.html?number={number}",
            "source": record.get("source") or "City of Nanaimo",
        })

    for changed in comparison.get("changed", []):
        number = str(changed.get("number") or "")
        fields = changed.get("fields") or {}
        record = {
            "number": number,
            "title": changed.get("title") or f"Bylaw {number}",
            "category": (
                fields.get("category", {}).get("after")
                or fields.get("category", {}).get("before")
                or "Other"
            ),
            "year": (
                fields.get("year", {}).get("after")
                or fields.get("year", {}).get("before")
            ),
            "legal_status": fields.get("legal_status", {}).get("after"),
            "relationships": fields.get("relationships", {}).get("after"),
        }
        changed_fields = sorted(fields)
        events.append({
            "id": f"{generated_at}:changed:{number}",
            "date": generated_at,
            "change_type": "changed",
            "status": classify_change_event("changed", record, fields),
            "number": number,
            "title": record["title"],
            "category": record["category"],
            "year": record["year"],
            "detail_url": f"detail.html?number={number}",
            "changed_fields": changed_fields,
            "source": "City of Nanaimo",
        })

    for record in comparison.get("removed", []):
        number = str(record.get("number") or "")
        events.append({
            "id": f"{generated_at}:removed:{number}",
            "date": generated_at,
            "change_type": "removed",
            "status": classify_change_event("removed", record),
            "number": number,
            "title": record.get("title") or f"Bylaw {number}",
            "category": record.get("category") or "Other",
            "year": record.get("year"),
            "detail_url": record.get("detail_url") or f"detail.html?number={number}",
            "source": record.get("source") or "City of Nanaimo",
        })

    return events


def build_baseline_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Seed the homepage with the newest official records until real diffs exist."""
    def sort_key(record: dict[str, Any]) -> tuple[int, tuple[int, ...]]:
        year = int(record.get("year") or 0)
        parts = tuple(int(part) for part in re.findall(r"\d+", str(record.get("number") or "")))
        return year, parts

    events: list[dict[str, Any]] = []
    for record in sorted(records, key=sort_key, reverse=True)[:40]:
        relationships = record.get("relationships") or {}
        legal_status = str(record.get("legal_status") or "Published")
        if legal_status in {"Repealed", "Replaced", "Repealing bylaw", "Replacement bylaw"}:
            status = "Repealed"
        elif legal_status == "Consolidated" or relationships.get("consolidates"):
            status = "Consolidated"
        elif legal_status == "Amendment bylaw" or relationships.get("amends"):
            status = "Amended"
        else:
            status = "New"
        year = int(record.get("year") or 0)
        events.append({
            "id": f"baseline:{record.get('number')}",
            "date": f"{year:04d}-01-01" if year else record.get("retrieved_at"),
            "date_precision": "year" if year else "collected",
            "change_type": "baseline",
            "status": status,
            "number": str(record.get("number") or ""),
            "title": record.get("title") or f"Bylaw {record.get('number')}",
            "category": record.get("category") or "Other",
            "year": record.get("year"),
            "detail_url": record.get("detail_url") or f"detail.html?number={record.get('number')}",
            "source": record.get("source") or "City of Nanaimo",
            "baseline": True,
        })
    return events


class CollectionProgress:
    """Lightweight single-line terminal progress display."""

    def __init__(self, total: int) -> None:
        self.total = max(int(total), 1)
        self.started = time.monotonic()
        self.failures = 0
        self.interactive = bool(getattr(sys.stdout, "isatty", lambda: False)())

    def update(self, current: int, *, number: str = "", failures: int | None = None, message: str = "") -> None:
        current = max(0, min(int(current), self.total))
        if failures is not None:
            self.failures = max(0, int(failures))
        elapsed = max(time.monotonic() - self.started, 0.001)
        rate = current / elapsed if current else 0.0
        eta = (self.total - current) / rate if rate > 0 else 0.0
        percent = current / self.total * 100
        width = 28
        filled = min(width, round(width * current / self.total))
        bar = "#" * filled + "-" * (width - filled)
        detail = f"Bylaw {number}" if number else message
        line = (
            f"[{bar}] {current:>3}/{self.total:<3} {percent:6.1f}% "
            f"| {detail:<18.18} | failures {self.failures} "
            f"| elapsed {self._format_time(elapsed)} | ETA {self._format_time(eta)}"
        )
        if self.interactive:
            print("\r" + line, end="", flush=True)
        else:
            print(line, flush=True)

    def note(self, message: str) -> None:
        if self.interactive:
            print()
        print(message, flush=True)

    def finish(self) -> None:
        self.update(self.total, failures=self.failures, message="Complete")
        if self.interactive:
            print()

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0, int(round(seconds)))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

def load_historical_bylaws() -> dict[str, dict[str, Any]]:
    """Load the newest known record for each bylaw from live and archived JSON."""
    sources = [OUT, *sorted(ARCHIVE_DIR.glob("*/*/bylaws.json"), reverse=True)]
    history: dict[str, dict[str, Any]] = {}
    for path in sources:
        payload = read_json(path, {})
        rows = payload if isinstance(payload, list) else payload.get("bylaws", [])
        for row in rows if isinstance(rows, list) else []:
            number = str(row.get("number") or "")
            if number and number not in history:
                history[number] = row
    return history


def probe_pdf_source(session: requests.Session, url: str) -> dict[str, Any]:
    """Check remote validators without downloading the PDF body."""
    try:
        response = session.head(url, timeout=60, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException:
        return {}
    return source_headers(response.headers, response.url)


def bylaw_archive_candidates(
    number: str,
    previous: dict[str, Any] | None,
    archive_index: PdfArchiveIndex,
) -> list[Path | None]:
    previous_archive = existing_path(ROOT, previous.get("pdf_archive_path") if previous else None)
    previous_hash = str((previous or {}).get("pdf_sha256") or "")
    archived_by_hash = archive_index.by_hash.get(previous_hash) if previous_hash else None
    archived_by_name = sorted(
        [
            *ARCHIVE_DIR.glob(f"*/*/pdf/{number}.pdf"),
            *ARCHIVE_DIR.glob(f"*/*/pdf/{number}-*.pdf"),
        ],
        reverse=True,
    )
    return [previous_archive, archived_by_hash, *archived_by_name, CURRENT_PDF_DIR / f"{number}.pdf"]


def ensure_bylaw_text(
    pdf_path: Path,
    archive_path: Path,
    previous: dict[str, Any] | None,
    *,
    force_extract: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Reuse sidecars, or freshly extract text from a new/changed local PDF."""
    current_text_path = (CURRENT_PDF_DIR / pdf_path.name).with_suffix(".txt")
    archive_text_path = archive_path.with_suffix(".txt")

    if not force_extract and current_text_path.is_file():
        text = current_text_path.read_text(encoding="utf-8", errors="replace")
        if text and not archive_text_path.is_file():
            archive_text_path.parent.mkdir(parents=True, exist_ok=True)
            archive_text_path.write_text(text, encoding="utf-8")
        return ({
            "text": text,
            "page_count": (previous or {}).get("pdf_page_count", 0),
            "method": (previous or {}).get("text_extraction_method") or "cached",
            "ocr_pages": (previous or {}).get("ocr_pages") or [],
            "warnings": (previous or {}).get("text_extraction_warnings") or ["Reused existing extracted text"],
        }, False)

    # An archive sidecar is tied to this exact archived PDF hash and remains
    # safe to reuse even when a stale live sidecar must be ignored.
    if archive_text_path.is_file():
        text = archive_text_path.read_text(encoding="utf-8", errors="replace")
        current_text_path.parent.mkdir(parents=True, exist_ok=True)
        current_text_path.write_text(text, encoding="utf-8")
        return ({
            "text": text,
            "page_count": (previous or {}).get("pdf_page_count", 0),
            "method": (previous or {}).get("text_extraction_method") or "cached-archive",
            "ocr_pages": (previous or {}).get("ocr_pages") or [],
            "warnings": ["Restored extracted text from the archive"],
        }, True)

    extraction = extract_pdf_text(pdf_path, enable_ocr=True, max_pages=300, max_characters=2_000_000)
    if extraction["text"]:
        current_text_path.parent.mkdir(parents=True, exist_ok=True)
        current_text_path.write_text(extraction["text"], encoding="utf-8")
        archive_text_path.parent.mkdir(parents=True, exist_ok=True)
        archive_text_path.write_text(extraction["text"], encoding="utf-8")
    return extraction, True


def collect_bylaw_pdf(
    session: requests.Session,
    record: dict[str, Any],
    previous: dict[str, Any] | None,
    snapshot_pdf_dir: Path,
    retrieved_at: str,
    archive_index: PdfArchiveIndex,
) -> tuple[str, str]:
    """Reuse an archived PDF unless the source is new or proven changed."""
    number = record["number"]
    current_path = CURRENT_PDF_DIR / f"{number}.pdf"
    desired_archive_path = snapshot_pdf_dir / f"{number}.pdf"
    existing = archive_index.find_first(bylaw_archive_candidates(number, previous, archive_index))

    previous_url = canonical_url((previous or {}).get("official_pdf"))
    current_url = canonical_url(record.get("official_pdf"))
    source_state = probe_pdf_source(session, record["official_pdf"]) if existing else {}
    source_changed = bool(previous_url and current_url and previous_url != current_url)
    source_changed = source_changed or remote_state_changed(
        previous,
        source_state,
        local_size=existing.stat().st_size if existing else None,
    )
    should_download = existing is None or source_changed

    action = "reused"
    content_changed = False
    if should_download:
        response = session.get(record["official_pdf"], timeout=120)
        response.raise_for_status()
        stored = archive_index.store_bytes(response.content, desired_archive_path)
        archive_path = stored.path
        copy_if_needed(archive_path, current_path)
        source_state = source_headers(response.headers, response.url)
        prior_hash = str((previous or {}).get("pdf_sha256") or "")
        content_changed = bool(prior_hash and prior_hash != stored.sha256)
        if stored.created:
            action = "downloaded-changed" if prior_hash else "downloaded-new"
        else:
            action = "downloaded-deduplicated"
    else:
        assert existing is not None
        digest, canonical_archive = archive_index.canonical_for_file(existing)
        if canonical_archive is None:
            stored = archive_index.ensure_file(existing, desired_archive_path)
            archive_path = stored.path
            action = "archive-repaired" if stored.created else "reused"
        else:
            archive_path = canonical_archive
        copy_if_needed(archive_path, current_path)

    previous_hash = str((previous or {}).get("pdf_sha256") or "")
    digest, canonical_archive = archive_index.canonical_for_file(archive_path)
    content_changed = should_download and previous_hash != digest
    extraction, text_repaired = ensure_bylaw_text(
        current_path,
        archive_path,
        previous,
        force_extract=content_changed,
    )
    archive_path = canonical_archive or archive_path

    record["local_pdf"] = f"pdf/{number}.pdf"
    record["local_text"] = f"pdf/{number}.txt" if extraction["text"] else None
    record["pdf_archive_path"] = archive_path.relative_to(ROOT).as_posix()
    record["pdf_sha256"] = digest
    record["pdf_retrieved_at"] = (retrieved_at if should_download else (previous or {}).get("pdf_retrieved_at")) or retrieved_at
    record["pdf_checked_at"] = retrieved_at
    record["pdf_page_count"] = extraction["page_count"]
    record["text_extraction_method"] = extraction["method"]
    record["ocr_pages"] = extraction["ocr_pages"]
    record["text_extraction_warnings"] = extraction["warnings"]
    record["pdf_archive_action"] = action
    record["text_repaired_from_local_pdf"] = bool(text_repaired)
    for key, value in source_state.items():
        if value not in (None, ""):
            record[key] = value
        elif previous and previous.get(key) not in (None, ""):
            record[key] = previous[key]
    return extraction["text"], action


def update_homepage_fallback(
    record_count: int,
    generated_at: str,
    amendment_count: int,
    repealed_or_replaced_count: int,
) -> None:
    """Keep server-rendered homepage totals synchronized with collected data.

    JavaScript still refreshes these values from data/bylaws.json, but this
    fallback prevents an old starter count from appearing when a script is
    cached, blocked, or fails before rendering.
    """
    if not HOMEPAGE.exists():
        return
    html = HOMEPAGE.read_text(encoding="utf-8")
    replacements = {
        "stat-online": f"{record_count:,}",
        "stat-connected": f"{record_count:,}",
        "stat-amended": f"{amendment_count:,}",
        "stat-repealed": f"{repealed_or_replaced_count:,}",
    }
    for element_id, value in replacements.items():
        html = re.sub(
            rf'(<strong\s+id=["\']{re.escape(element_id)}["\'][^>]*>).*?(</strong>)',
            rf'\g<1>{value}\g<2>',
            html,
            count=1,
            flags=re.S,
        )
    html = re.sub(
        r'(<strong\s+id=["\']stat-connected["\'][^>]*>.*?</strong><b>records connected</b><small>).*?(</small>)',
        rf'\g<1>{record_count:,} records archived\g<2>',
        html,
        count=1,
        flags=re.S,
    )
    html = re.sub(
        r'(<small\s+id=["\']dataset-updated["\'][^>]*>).*?(</small>)',
        rf'\g<1>Dataset updated: {generated_at}\g<2>',
        html,
        count=1,
        flags=re.S,
    )
    HOMEPAGE.write_text(html, encoding="utf-8")


def collect(download_pdfs: bool = False) -> None:
    run_time = now_local()
    date_stamp = run_time.strftime("%Y-%m-%d")
    time_stamp = run_time.strftime("%H%M%S")
    generated_at = run_time.isoformat(timespec="seconds")
    snapshot_dir = ARCHIVE_DIR / date_stamp / time_stamp
    snapshot_json = snapshot_dir / "bylaws.json"
    snapshot_pdf_dir = snapshot_dir / "pdf"

    session = requests.Session()
    session.headers["User-Agent"] = "NanaimoBylawTracker/0.1 (+independent civic archive)"
    response = session.get(INDEX, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    historical_records = load_historical_bylaws()
    archive_index = PdfArchiveIndex(ARCHIVE_DIR)
    pdf_actions: dict[str, int] = {}
    text_repairs = 0

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchors = list(soup.select('a[href*="ViewBylaw"]'))
    progress = CollectionProgress(len(anchors))
    pdf_failures = 0
    progress.update(0, message="Starting")
    for anchor_index, anchor in enumerate(anchors, start=1):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(INDEX, anchor.get("href", ""))
        number = number_from(title, href)
        if not number or number in seen:
            progress.update(anchor_index, number=number or "Skipped", failures=pdf_failures)
            continue
        seen.add(number)

        description = ""
        node = anchor.find_parent()
        if node:
            description = " ".join(node.get_text(" ", strip=True).replace(title, "", 1).split())
        year_match = re.search(r"\b(19|20)\d{2}\b", title)
        record: dict[str, Any] = {
            "number": number,
            "title": title,
            "description": description,
            "year": int(year_match.group()) if year_match else None,
            "category": category(f"{title} {description}"),
            "status": "Published",
            "official_pdf": href,
            "official_index": INDEX,
            "local_pdf": f"pdf/{number}.pdf",
            "detail_url": f"detail.html?number={number}",
            "source": "City of Nanaimo",
            "last_checked": date_stamp,
            "retrieved_at": generated_at,
        }
        relationship_text = f"{title}\n{description}"
        previous_record = historical_records.get(number)
        if download_pdfs:
            try:
                extracted_text, action = collect_bylaw_pdf(
                    session, record, previous_record, snapshot_pdf_dir, generated_at, archive_index
                )
                pdf_actions[action] = pdf_actions.get(action, 0) + 1
                if record.get("text_repaired_from_local_pdf"):
                    text_repairs += 1
                if extracted_text:
                    relationship_text += f"\n{extracted_text}"
                time.sleep(0.05)
            except Exception as exc:  # continue collection if one source file fails
                record["pdf_download_error"] = str(exc)
                if previous_record:
                    for key, value in previous_record.items():
                        if key.startswith(("pdf_", "text_extraction_", "source_")) or key in {"local_text", "ocr_pages"}:
                            record.setdefault(key, value)
                pdf_failures += 1
                progress.note(f"PDF {number} failed: {exc}")
        else:
            if previous_record:
                for key, value in previous_record.items():
                    if key.startswith(("pdf_", "text_extraction_", "source_")) or key in {"local_text", "ocr_pages"}:
                        record.setdefault(key, value)
            existing_text = CURRENT_PDF_DIR / f"{number}.txt"
            if existing_text.exists():
                relationship_text += "\n" + existing_text.read_text(
                    encoding="utf-8", errors="replace"
                )
        record["relationships"] = infer_relationships(number, relationship_text)
        records.append(record)
        progress.update(anchor_index, number=number, failures=pdf_failures)

    progress.finish()
    records.sort(key=lambda item: (item["title"], item["number"]))
    relationship_graph = build_relationship_graph(records)

    amendment_bylaw_count = sum(
        1 for record in records
        if record.get("legal_status") == "Amendment bylaw"
        or bool((record.get("relationships") or {}).get("amends"))
    )
    collected_repealed_or_replaced_count = relationship_graph[
        "collected_repealed_or_replaced_count"
    ]
    historical_repealed_or_replaced_count = relationship_graph[
        "historical_repealed_or_replaced_count"
    ]
    repealed_or_replaced_count = (
        collected_repealed_or_replaced_count
        + historical_repealed_or_replaced_count
    )

    relationship_graph.update({
        "generated_at": generated_at,
        "timezone": "America/Vancouver",
        "source": INDEX,
        "relationship_edges": relationship_graph["edge_count"],
        "amendment_bylaw_count": amendment_bylaw_count,
        "repealed_or_replaced_count": repealed_or_replaced_count,
        "collected_repealed_or_replaced_count": collected_repealed_or_replaced_count,
        "historical_repealed_or_replaced_count": historical_repealed_or_replaced_count,
    })

    previous_path = previous_snapshot(snapshot_dir)
    previous_payload = read_json(previous_path, {}) if previous_path else {}
    comparison = compare_records(previous_payload.get("bylaws", []), records)
    comparison.update({
        "generated_at": generated_at,
        "timezone": "America/Vancouver",
        "snapshot": str(snapshot_dir.relative_to(ROOT)).replace("\\", "/"),
        "compared_to": (
            str(previous_path.parent.relative_to(ROOT)).replace("\\", "/")
            if previous_path else None
        ),
    })

    payload = {
        "metadata": {
            "official_result_count": len(records),
            "records_included": len(records),
            "generated": date_stamp,
            "generated_at": generated_at,
            "timezone": "America/Vancouver",
            "source": INDEX,
            "snapshot": str(snapshot_dir.relative_to(ROOT)).replace("\\", "/"),
            "pdfs_archived": download_pdfs,
            "pdf_archive_actions": pdf_actions,
            "pdf_text_repairs": text_repairs,
            "preexisting_duplicate_archive_files_detected": archive_index.duplicate_file_count,
            "note": "Generated from the City of Nanaimo public bylaw index. Existing archived PDFs are reused; only new or remotely changed content is stored.",
        },
        "bylaws": records,
    }

    # Preserve the immutable run first, then update the live site files.
    write_json(snapshot_json, payload)
    write_json(snapshot_dir / "changes.json", comparison)
    write_json(OUT, payload)
    write_json(RELATIONSHIPS, relationship_graph)
    write_json(snapshot_dir / "bylaw-relationships.json", relationship_graph)
    write_json(SUMMARY, {
        "record_count": len(records),
        "generated_at": generated_at,
        "timezone": "America/Vancouver",
        "source": INDEX,
        "relationship_edges": relationship_graph["edge_count"],
        "amendment_bylaw_count": amendment_bylaw_count,
        "repealed_or_replaced_count": repealed_or_replaced_count,
        "collected_repealed_or_replaced_count": collected_repealed_or_replaced_count,
        "historical_repealed_or_replaced_count": historical_repealed_or_replaced_count,
        "relationship_count_method": "Explicit repeal/replacement relationships extracted from official titles, descriptions, and PDF text",
    })
    update_homepage_fallback(
        len(records),
        generated_at,
        amendment_bylaw_count,
        repealed_or_replaced_count,
    )

    log = read_json(
        CHANGE_LOG,
        {"timezone": "America/Vancouver", "runs": [], "events": []},
    )
    runs = log.setdefault("runs", [])
    events = log.setdefault("events", [])
    run_events = build_change_events(comparison, generated_at)
    if not events and not run_events:
        run_events = build_baseline_events(records)

    runs.append({
        "generated_at": generated_at,
        "snapshot": comparison["snapshot"],
        "compared_to": comparison["compared_to"],
        **comparison["summary"],
        "event_count": len(run_events),
    })
    events.extend(run_events)

    # Keep the newest real events and a bounded run history.
    log["events"] = sorted(
        events,
        key=lambda item: str(item.get("date") or ""),
        reverse=True,
    )[:500]
    log["runs"] = runs[-365:]
    log["last_updated"] = generated_at
    log["event_count"] = len(log["events"])
    write_json(CHANGE_LOG, log)

    print(f"Wrote {len(records)} live records to {OUT}")
    print(f"Archived snapshot at {snapshot_dir}")
    if download_pdfs:
        print("PDF archive actions: " + ", ".join(f"{key}={value}" for key, value in sorted(pdf_actions.items())))
        print(f"Text sidecars repaired from local PDFs: {text_repairs}")
        if archive_index.duplicate_file_count:
            print(f"Warning: detected {archive_index.duplicate_file_count} pre-existing duplicate archive PDFs; no new duplicate PDF was written.")
    print(f"Tracked {relationship_graph['edge_count']} amendment/repeal/replacement relationships")
    print(
        f"Identified {repealed_or_replaced_count} repealed/replaced bylaws: "
        f"{collected_repealed_or_replaced_count} collected and "
        f"{historical_repealed_or_replaced_count} historical references"
    )
    print(
        "Changes: "
        f"{comparison['summary']['added']} added, "
        f"{comparison['summary']['changed']} changed, "
        f"{comparison['summary']['removed']} removed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-pdfs", action="store_true")
    args = parser.parse_args()
    collect(args.download_pdfs)
