#!/usr/bin/env python3
"""Verify Nanaimo Council collection output.

Checks the latest Council datasets for structural integrity, extraction quality,
duplicate records, dates, source links, bylaw matching, timeline readiness, and
featured-bylaw consistency.

Exit codes:
  0 = pass or warnings only
  1 = critical verification failure
  2 = verifier could not run
"""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("America/Vancouver")

MEETINGS = DATA / "council-meetings.json"
DOCUMENTS = DATA / "council-documents.json"
ITEMS = DATA / "council-items.json"
DISCUSSIONS = DATA / "council-discussions.json"
FEATURED = DATA / "featured.json"
BYLAWS = DATA / "bylaws.json"
REPORT = DATA / "council-verification.json"

VALID_ACTIONS = {
    "Adopted", "Passed", "First Reading", "Second Reading", "Third Reading",
    "Three Readings", "Reading", "Amended", "Deferred", "Directed",
    "Approved", "Endorsed", "Received", "Referred", "Denied", "Rescinded",
    "Discussed",
}


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def records(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return [item for item in value if isinstance(item, dict)]
    return []


def add(
    checks: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    details: Any = None,
) -> None:
    item = {"severity": severity, "code": code, "message": message}
    if details not in (None, [], {}, ""):
        item["details"] = details
    checks.append(item)


def valid_date(value: Any) -> bool:
    if not value:
        return False
    try:
        datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


def valid_url(value: Any) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def verify(strict: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    payloads = {
        "meetings": read_json(MEETINGS),
        "documents": read_json(DOCUMENTS),
        "items": read_json(ITEMS),
        "discussions": read_json(DISCUSSIONS),
        "featured": read_json(FEATURED),
        "bylaws": read_json(BYLAWS),
    }

    required = {
        "meetings": MEETINGS,
        "documents": DOCUMENTS,
        "items": ITEMS,
        "discussions": DISCUSSIONS,
    }
    for name, path in required.items():
        if payloads[name] is None:
            add(checks, "fail", f"missing-{name}", f"Missing or invalid {path.relative_to(ROOT)}")

    meetings = records(payloads["meetings"], "meetings")
    documents = records(payloads["documents"], "documents")
    items = records(payloads["items"], "items")
    discussions = records(payloads["discussions"], "items")
    bylaws = records(payloads["bylaws"], "bylaws")
    featured = payloads["featured"] if isinstance(payloads["featured"], dict) else {}

    if not meetings:
        add(checks, "fail", "no-meetings", "No Council meetings were discovered.")
    else:
        add(checks, "pass", "meetings-found", f"Discovered {len(meetings)} Council meetings.")

    dated_meetings = [meeting for meeting in meetings if valid_date(meeting.get("date"))]
    undated_meetings = [meeting for meeting in meetings if not valid_date(meeting.get("date"))]
    if meetings and len(dated_meetings) / len(meetings) < 0.85:
        add(
            checks,
            "warn",
            "meeting-date-coverage",
            f"Only {len(dated_meetings)} of {len(meetings)} meetings have valid dates.",
            [meeting.get("meeting_url") for meeting in undated_meetings[:20]],
        )
    elif meetings:
        add(checks, "pass", "meeting-date-coverage", f"{len(dated_meetings)} meetings have valid dates.")

    meeting_urls = [meeting.get("meeting_url") for meeting in meetings if meeting.get("meeting_url")]
    duplicate_meeting_urls = [url for url, count in Counter(meeting_urls).items() if count > 1]
    if duplicate_meeting_urls:
        add(checks, "warn", "duplicate-meetings", "Duplicate meeting URLs were found.", duplicate_meeting_urls[:20])
    else:
        add(checks, "pass", "duplicate-meetings", "No duplicate meeting URLs found.")

    if not documents:
        add(checks, "fail", "no-documents", "No Council documents were discovered.")
    else:
        add(checks, "pass", "documents-found", f"Discovered {len(documents)} Council documents.")

    document_urls = [document.get("url") for document in documents if document.get("url")]
    duplicate_document_urls = [url for url, count in Counter(document_urls).items() if count > 1]
    if duplicate_document_urls:
        add(checks, "warn", "duplicate-documents", "Duplicate document URLs were found.", duplicate_document_urls[:20])
    else:
        add(checks, "pass", "duplicate-documents", "No duplicate document URLs found.")

    broken_urls = [
        document.get("url")
        for document in documents
        if document.get("url") and not valid_url(document.get("url"))
    ]
    if broken_urls:
        add(checks, "fail", "invalid-document-urls", "Invalid Council document URLs found.", broken_urls[:20])
    elif documents:
        add(checks, "pass", "document-urls", "Council document URLs are structurally valid.")

    failed_downloads = [
        {
            "url": document.get("url"),
            "error": document.get("download_error"),
        }
        for document in documents
        if document.get("download_error")
    ]
    if failed_downloads:
        severity = "fail" if len(failed_downloads) == len(documents) else "warn"
        add(
            checks,
            severity,
            "download-failures",
            f"{len(failed_downloads)} Council documents failed to download.",
            failed_downloads[:30],
        )
    elif documents:
        add(checks, "pass", "download-failures", "No recorded Council document download failures.")

    downloaded = [
        document for document in documents
        if document.get("local_path") or document.get("local_document")
    ]
    extracted = [
        document for document in documents
        if document.get("text_path") or document.get("character_count", 0)
    ]
    if documents and not downloaded:
        add(
            checks,
            "warn",
            "pdf-download-mode",
            "No local Council PDFs are recorded. Run with --download for full verification."
        )
    elif downloaded:
        add(checks, "pass", "pdf-download-mode", f"{len(downloaded)} documents have local PDF records.")

    extraction_methods = Counter(
        str(document.get("text_extraction_method") or "none")
        for document in documents
    )
    sparse_documents = [
        {
            "url": document.get("url"),
            "method": document.get("text_extraction_method"),
            "ocr_error": document.get("ocr_error"),
            "warnings": document.get("text_extraction_warnings"),
        }
        for document in documents
        if (
            document.get("local_path")
            and not document.get("text_path")
            and not document.get("character_count")
        )
    ]
    if downloaded and len(extracted) / len(downloaded) < 0.70:
        add(
            checks,
            "warn",
            "text-extraction-coverage",
            f"Only {len(extracted)} of {len(downloaded)} downloaded documents produced text.",
            sparse_documents[:30],
        )
    elif downloaded:
        add(
            checks,
            "pass",
            "text-extraction-coverage",
            f"{len(extracted)} of {len(downloaded)} downloaded documents produced text.",
            dict(extraction_methods),
        )

    ocr_failures = [
        {
            "url": document.get("url"),
            "ocr_error": document.get("ocr_error"),
        }
        for document in documents
        if document.get("ocr_error")
    ]
    if ocr_failures:
        add(
            checks,
            "warn",
            "ocr-failures",
            f"OCR fallback reported issues for {len(ocr_failures)} documents.",
            ocr_failures[:30],
        )
    elif any(document.get("ocr_pages") for document in documents):
        add(checks, "pass", "ocr-failures", "OCR fallback completed without recorded errors.")

    if not items:
        add(checks, "fail", "no-items", "No Council bylaw or motion items were extracted.")
    else:
        add(checks, "pass", "items-found", f"Extracted {len(items)} Council items.")

    item_ids = [item.get("id") for item in items if item.get("id")]
    duplicate_item_ids = [item_id for item_id, count in Counter(item_ids).items() if count > 1]
    if duplicate_item_ids:
        add(checks, "fail", "duplicate-item-ids", "Duplicate Council item IDs found.", duplicate_item_ids[:20])
    else:
        add(checks, "pass", "duplicate-item-ids", "No duplicate Council item IDs found.")

    invalid_actions = sorted({
        str(item.get("action"))
        for item in items
        if item.get("action") and str(item.get("action")) not in VALID_ACTIONS
    })
    if invalid_actions:
        add(checks, "warn", "unknown-actions", "Unrecognized Council action labels found.", invalid_actions)
    elif items:
        add(checks, "pass", "unknown-actions", "Council action labels are recognized.")

    dated_items = [item for item in items if valid_date(item.get("date"))]
    if items and len(dated_items) / len(items) < 0.80:
        add(
            checks,
            "warn",
            "item-date-coverage",
            f"Only {len(dated_items)} of {len(items)} Council items have valid dates."
        )
    elif items:
        add(checks, "pass", "item-date-coverage", f"{len(dated_items)} Council items have valid dates.")

    bylaw_numbers = {str(record.get("number")) for record in bylaws if record.get("number")}
    bylaw_items = [item for item in items if item.get("type") == "Bylaw"]
    matched_items = [
        item for item in bylaw_items
        if str(item.get("number") or "") in bylaw_numbers
        or str(item.get("base_number") or "") in bylaw_numbers
    ]
    unmatched_items = [
        {
            "number": item.get("number"),
            "base_number": item.get("base_number"),
            "title": item.get("title"),
            "date": item.get("date"),
        }
        for item in bylaw_items
        if item not in matched_items
    ]
    if bylaw_items and len(matched_items) / len(bylaw_items) < 0.50:
        add(
            checks,
            "warn",
            "bylaw-match-rate",
            f"Only {len(matched_items)} of {len(bylaw_items)} extracted bylaw items match the local bylaw index.",
            unmatched_items[:30],
        )
    elif bylaw_items:
        add(
            checks,
            "pass",
            "bylaw-match-rate",
            f"{len(matched_items)} of {len(bylaw_items)} extracted bylaw items match the local bylaw index."
        )

    if len(discussions) > 40:
        add(checks, "fail", "discussion-limit", f"Homepage discussions contains {len(discussions)} items; maximum is 40.")
    elif discussions:
        add(checks, "pass", "discussion-limit", f"Homepage discussions contains {len(discussions)} items.")

    discussion_dates = [str(item.get("date") or "") for item in discussions]
    if discussion_dates != sorted(discussion_dates, reverse=True):
        add(checks, "warn", "discussion-order", "Homepage Council discussions are not sorted newest first.")
    elif discussions:
        add(checks, "pass", "discussion-order", "Homepage Council discussions are sorted newest first.")

    if not featured:
        add(checks, "warn", "featured-missing", "No automatic featured bylaw record was generated.")
    else:
        featured_number = str(featured.get("base_bylaw_number") or "")
        source_match = any(
            str(item.get("base_number") or item.get("number") or "") == featured_number
            for item in bylaw_items
        )
        if not featured_number:
            add(checks, "fail", "featured-number", "Featured bylaw has no base bylaw number.")
        elif not source_match:
            add(
                checks,
                "warn",
                "featured-source-match",
                f"Featured bylaw {featured_number} does not match an extracted Council bylaw item."
            )
        else:
            add(
                checks,
                "pass",
                "featured-source-match",
                f"Featured bylaw {featured_number} matches collected Council activity."
            )

    metadata = payloads["items"].get("metadata", {}) if isinstance(payloads["items"], dict) else {}
    generated_at = metadata.get("generated_at")
    if generated_at:
        try:
            generated = datetime.fromisoformat(str(generated_at))
            age_hours = (datetime.now(TZ) - generated.astimezone(TZ)).total_seconds() / 3600
            if age_hours > 48:
                add(checks, "warn", "collection-age", f"Council datasets are {age_hours:.1f} hours old.")
            else:
                add(checks, "pass", "collection-age", f"Council datasets are {age_hours:.1f} hours old.")
        except ValueError:
            add(checks, "warn", "collection-age", "Council metadata has an invalid generated_at value.")

    counts = Counter(check["severity"] for check in checks)
    critical_failures = counts.get("fail", 0)
    warnings = counts.get("warn", 0)
    status = "fail" if critical_failures else ("warn" if warnings else "pass")
    if strict and warnings:
        status = "fail"

    report = {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "timezone": "America/Vancouver",
        "status": status,
        "strict": strict,
        "summary": {
            "pass": counts.get("pass", 0),
            "warn": warnings,
            "fail": critical_failures,
            "meetings": len(meetings),
            "documents": len(documents),
            "downloaded_documents": len(downloaded),
            "text_documents": len(extracted),
            "items": len(items),
            "bylaw_items": len(bylaw_items),
            "matched_bylaw_items": len(matched_items),
            "discussions": len(discussions),
        },
        "checks": checks,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def print_report(report: dict[str, Any]) -> None:
    symbols = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    print("\nCouncil collection verification")
    print("=" * 31)
    for check in report["checks"]:
        print(f"[{symbols[check['severity']]}] {check['message']}")
    summary = report["summary"]
    print("-" * 31)
    print(
        f"Status: {report['status'].upper()} | "
        f"{summary['meetings']} meetings | "
        f"{summary['documents']} documents | "
        f"{summary['items']} items | "
        f"{summary['matched_bylaw_items']}/{summary['bylaw_items']} bylaw matches"
    )
    print(f"Report: {REPORT}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as verification failures.",
    )
    args = parser.parse_args()
    try:
        result = verify(strict=args.strict)
        print_report(result)
        raise SystemExit(1 if result["status"] == "fail" else 0)
    except Exception as exc:
        print(f"Council verification could not run: {exc}", file=sys.stderr)
        raise SystemExit(2)
