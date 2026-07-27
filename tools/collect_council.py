#!/usr/bin/env python3
"""Collect Nanaimo Council meetings, PDFs, summaries, bylaws and motions.

Creates reusable structured datasets:

  data/council-meetings.json
  data/council-documents.json
  data/council-items.json
  data/council-discussions.json

Downloaded source files are stored under:

  council/YYYY-MM-DD/<meeting-slug>/
  archive/council/YYYY-MM-DD/HHMMSS/

Usage:
  python tools/collect_council.py
  python tools/collect_council.py --download
  python tools/collect_council.py --download --years 2026 2025

The collector combines official eSCRIBE meeting documents with City of Nanaimo
Council summaries. PDF extraction uses pypdf when installed.
"""
from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
import json
import re
import shutil
import subprocess
import sys
import time

import requests
from bs4 import BeautifulSoup

from pdf_text import extract_pdf_text as extract_pdf_text_with_ocr
from archive_cache import (
    PdfArchiveIndex,
    copy_if_needed,
    existing_path,
    remote_state_changed,
    source_headers,
)
from bylaw_relationships import infer_relationships, relationship_targets

try:
    import fitz
except ImportError:
    fitz = None

try:
    from pypdf import PdfReader
except ImportError:  # PDF files still download; extraction is marked unavailable.
    PdfReader = None

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Vancouver")
ESCRIBE = "https://pub-nanaimo.escribemeetings.com/?MeetingViewId=1&Year=Current&fillWidth=1"
ESCRIBE_CALENDAR = "https://pub-nanaimo.escribemeetings.com/MeetingsCalendarView.aspx"
CITY_MEETINGS = "https://www.nanaimo.ca/your-government/city-council/council-meetings/meeting-documents-and-videos"
SUMMARIES = "https://www.nanaimo.ca/your-government/city-council/council-meetings/summaries"

DATA_DIR = ROOT / "data"
COUNCIL_DIR = ROOT / "council"
ARCHIVE_DIR = ROOT / "archive" / "council"
BYLAWS_JSON = DATA_DIR / "bylaws.json"
MEETINGS_JSON = DATA_DIR / "council-meetings.json"
DOCUMENTS_JSON = DATA_DIR / "council-documents.json"
ITEMS_JSON = DATA_DIR / "council-items.json"
COMMITTEE_ITEMS_JSON = DATA_DIR / "committee-items.json"
COMMITTEE_INDEX_JSON = DATA_DIR / "committee-index.json"
DISCUSSIONS_JSON = DATA_DIR / "council-discussions.json"
FEATURED_JSON = DATA_DIR / "featured.json"
CHANGE_LOG = DATA_DIR / "council-change-log.json"
PROGRESS_JSON = DATA_DIR / "council-collector-progress.json"
MAX_PARSE_CHARS = 2_000_000
MAX_CHUNK_CHARS = 2400

MEETING_TYPES = (
    "Regular Council",
    "Special Council",
    "Public Hearing",
    "Governance and Priorities",
    "Finance and Audit",
    "Public Safety Committee",
    "Advisory Committee",
    "Committee",
    "Board",
    "Commission",
    "Panel",
    "Task Force",
    "Working Group",
)



def meeting_title_candidate(text: str, context: str) -> str:
    """Preserve the published body name instead of collapsing it to a generic type."""
    candidates = [normalize_space(text), normalize_space(context)]
    marker = re.compile(r"(?:committee|board|commission|panel|task force|working group|council|public hearing)", re.I)
    date_tail = re.compile(
        r"\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?[,]?\s*"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},\s+\d{4}.*$",
        re.I,
    )
    for candidate in candidates:
        if not candidate or not marker.search(candidate):
            continue
        candidate = date_tail.sub("", candidate).strip(" -|–—")
        candidate = re.sub(r"\s+(?:agenda|minutes|video|documents?).*$", "", candidate, flags=re.I).strip(" -|–—")
        if 3 <= len(candidate) <= 180:
            return candidate
    return normalize_space(text) or "Council meeting"

def classify_meeting(title: str) -> tuple[str, str]:
    normalized = normalize_space(title).lower()
    if "public hearing" in normalized:
        return "Public Hearing", "public-hearing"
    if "regular council" in normalized:
        return "Regular Council", "council"
    if "special council" in normalized:
        return "Special Council", "council"
    if "governance and priorities" in normalized:
        return "Governance and Priorities Committee", "committee"
    if "finance and audit" in normalized:
        return "Finance and Audit Committee", "committee"
    if "committee" in normalized:
        return normalize_space(title) or "Committee meeting", "committee"
    if "board" in normalized:
        return normalize_space(title) or "Board meeting", "board"
    if "commission" in normalized:
        return normalize_space(title) or "Commission meeting", "commission"
    if "panel" in normalized:
        return normalize_space(title) or "Panel meeting", "panel"
    if "task force" in normalized or "working group" in normalized:
        return normalize_space(title) or "Advisory group meeting", "committee"
    return normalize_space(title) or "Council meeting", "council"
ACTION_TERMS = (
    "adopted", "passed", "reading", "rescinded", "amended", "deferred",
    "directed", "approved", "endorsed", "received", "referred", "denied",
)
MOTION_PREFIXES = (
    "Council directed", "Council approved", "Council endorsed",
    "Council adopted", "Council deferred", "Council referred",
    "Council denied", "Council received", "Council supported",
)
BYLAW_NUMBER_RE = re.compile(
    r'\bBylaw(?:\s+Amendment)?(?:\s+\d{4})?\s+(?:No\.?\s*)?(?P<number>\d{3,4}(?:\.\d+)*)',
    re.I,
)
DATE_PATTERNS = (
    "%A, %B %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%Y-%b-%d",
)



def canonical_url(value: str | None) -> str:
    """Normalize source URLs for reliable deduplication and resume lookups."""
    if not value:
        return ""
    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    query_parts = [part for part in parsed.query.split("&") if part and not part.lower().startswith(("fillwidth=", "_="))]
    query = "&".join(sorted(query_parts, key=str.lower))
    return f"{scheme}://{host}{path}" + (f"?{query}" if query else "")


def existing_file(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = ROOT / relative_path
    return candidate if candidate.is_file() else None


def load_resume_state(years: list[int], download: bool) -> dict[str, Any]:
    state = read_json(PROGRESS_JSON, {})
    if state.get("years") != years or bool(state.get("download", state.get("download_pdfs"))) != bool(download):
        return {"documents": [], "items": []}
    return state


def save_resume_state(years: list[int], download: bool, documents: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
    write_json(PROGRESS_JSON, {
        "updated_at": now_local().isoformat(timespec="seconds"),
        "years": years,
        "download": download,
        "documents": documents,
        "items": items,
    })

def now_local() -> datetime:
    return datetime.now(TZ)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_historical_documents() -> dict[str, dict[str, Any]]:
    """Load the newest document record for each canonical source URL."""
    sources = [DOCUMENTS_JSON, *sorted(ARCHIVE_DIR.glob("*/*/council-documents.json"), reverse=True)]
    history: dict[str, dict[str, Any]] = {}
    for path in sources:
        payload = read_json(path, {})
        rows = payload if isinstance(payload, list) else payload.get("documents", [])
        for row in rows if isinstance(rows, list) else []:
            key = canonical_url(row.get("url"))
            if key and key not in history:
                history[key] = row
    return history


def probe_document_source(session: requests.Session, url: str) -> dict[str, Any]:
    """Read source validators with HEAD; never fetch an existing PDF body."""
    try:
        response = session.head(url, timeout=90, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException:
        return {}
    return source_headers(response.headers, response.url)


def normalize_space(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:100] or "meeting"


def parse_date(text: str) -> str | None:
    cleaned = normalize_space(text)
    candidates = [
        re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}", cleaned),
        re.search(r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}", cleaned),
        re.search(r"\d{4}-[A-Z][a-z]{2}-\d{2}", cleaned),
        re.search(r"\d{4}-\d{2}-\d{2}", cleaned),
    ]
    for match in candidates:
        if not match:
            continue
        raw = match.group(0)
        for pattern in DATE_PATTERNS:
            try:
                return datetime.strptime(raw, pattern).date().isoformat()
            except ValueError:
                pass
    return None


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bylaw_lookup() -> dict[str, dict[str, Any]]:
    payload = read_json(BYLAWS_JSON, {})
    records = payload if isinstance(payload, list) else payload.get("bylaws", [])
    lookup: dict[str, dict[str, Any]] = {}
    for record in records:
        number = str(record.get("number", ""))
        if number:
            lookup[number] = record
    return lookup


def source_get(session: requests.Session, url: str, timeout: int = 90) -> requests.Response:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response


def discover_escribe_meetings(session: requests.Session, years: list[int]) -> list[dict[str, Any]]:
    urls = [ESCRIBE, ESCRIBE_CALENDAR]
    for year in years:
        urls.extend([
            f"https://pub-nanaimo.escribemeetings.com/?MeetingViewId=1&Year={year}&fillWidth=1",
            f"{ESCRIBE_CALENDAR}?Year={year}",
        ])
    urls = list(dict.fromkeys(urls))

    meetings: dict[str, dict[str, Any]] = {}
    for index_url in urls:
        try:
            soup = BeautifulSoup(source_get(session, index_url).text, "html.parser")
        except Exception as exc:
            print(f"Meeting index failed: {index_url}: {exc}")
            continue

        # eSCRIBE links vary over time, so collect any links that look meeting-specific.
        for anchor in soup.find_all("a", href=True):
            text = normalize_space(anchor.get_text(" ", strip=True))
            href = urljoin(index_url, anchor["href"])
            context = normalize_space(anchor.parent.get_text(" ", strip=True) if anchor.parent else text)
            combined = f"{text} {context}"
            if not any(kind.lower() in combined.lower() for kind in MEETING_TYPES):
                continue
            if not any(token in href.lower() for token in ("meeting", "agenda", "id=")):
                continue
            meeting_date = parse_date(combined)
            key = href.split("#", 1)[0]
            detected_title = meeting_title_candidate(text, context)
            meeting_title, meeting_group = classify_meeting(detected_title)
            current = meetings.setdefault(key, {
                "meeting_url": key,
                "title": meeting_title,
                "meeting_group": meeting_group,
                "date": meeting_date,
                "source": "City of Nanaimo eSCRIBE",
                "documents": [],
            })
            if not current.get("date") and meeting_date:
                current["date"] = meeting_date

        # Some eSCRIBE list pages expose document links without a separate meeting link.
        blocks = soup.find_all(["article", "li", "div"])
        for block in blocks:
            context = normalize_space(block.get_text(" ", strip=True))
            if not any(kind.lower() in context.lower() for kind in MEETING_TYPES):
                continue
            meeting_date = parse_date(context)
            document_links = [
                urljoin(index_url, a["href"])
                for a in block.find_all("a", href=True)
                if is_document_link(normalize_space(a.get_text(" ", strip=True)), a["href"])
            ]
            if not document_links:
                continue
            detected_title = meeting_title_candidate("", context)
            title, meeting_group = classify_meeting(detected_title)
            key = f"{meeting_date or 'undated'}-{slugify(title)}"
            record = meetings.setdefault(key, {
                "meeting_url": index_url,
                "title": title,
                "meeting_group": meeting_group,
                "date": meeting_date,
                "source": "City of Nanaimo eSCRIBE",
                "documents": [],
            })
            record["documents"].extend(document_links)

    return sorted(meetings.values(), key=lambda item: item.get("date") or "", reverse=True)


def classify_document(label: str, url: str) -> str:
    text = f"{label} {url}".lower()
    if "revised" in text and "agenda" in text:
        return "revised-agenda"
    if "minute" in text:
        return "minutes"
    if "notice" in text:
        return "notice"
    if "agenda" in text:
        return "agenda"
    if "report" in text:
        return "report"
    return "attachment"



def is_document_link(label: str, href: str) -> bool:
    label_text = normalize_space(label).lower()
    parsed = urlparse(urljoin(ESCRIBE, href))
    path_name = Path(parsed.path).name.lower()
    combined = f"{label_text} {href}".lower()

    # eSCRIBE meeting pages contain navigation/forms that are not public records.
    blocked_handlers = {
        "sharing.aspx",
        "meeting.aspx",
        "delegationrequest.aspx",
        "login.aspx",
        "register.aspx",
        "calendar.aspx",
    }
    if path_name in blocked_handlers:
        return False
    if any(token in combined for token in (
        "meetingview", "delegation request", "share this meeting",
        "calendar", "video", "youtube", "webcast", "subscribe",
    )):
        return False

    # Require a meaningful record label or a known downloadable handler.
    meaningful = any(token in label_text for token in (
        "agenda", "minutes", "minute", "notice", "report",
        "attachment", "package", "document", "supplemental", "revised",
    ))
    downloadable = (
        path_name.endswith((".pdf", ".ashx"))
        or "download" in combined
        or "document" in path_name
        or "attachment" in path_name
    )
    return meaningful or downloadable


def pdf_bytes(content: bytes) -> bool:
    return content.lstrip().startswith(b"%PDF-")


def html_document_candidates(base_url: str, content: bytes) -> list[str]:
    soup = BeautifulSoup(content, "html.parser")
    candidates: list[str] = []
    for element in soup.find_all(["a", "iframe", "embed", "object"], href=True):
        candidates.append(urljoin(base_url, element.get("href")))
    for element in soup.find_all(["iframe", "embed", "object"], src=True):
        candidates.append(urljoin(base_url, element.get("src")))
    for element in soup.find_all("object", data=True):
        candidates.append(urljoin(base_url, element.get("data")))
    text = content.decode("utf-8", errors="ignore")
    candidates.extend(urljoin(base_url, value) for value in re.findall(
        r"(?:href|src|data)=[\"\']([^\"\']+)[\"\']", text, flags=re.I
    ))
    ranked=[]
    for url in dict.fromkeys(candidates):
        lower=url.lower()
        if any(token in lower for token in (".pdf", "download", "document", ".aspx")):
            ranked.append(url)
    return ranked


def resolve_public_document(
    session: requests.Session,
    url: str,
    *,
    depth: int = 0,
    seen: set[str] | None = None,
) -> dict[str, Any]:
    seen = seen or set()
    if url in seen or depth > 3:
        raise RuntimeError("Document resolver reached a loop or depth limit")
    seen.add(url)
    response = source_get(session, url, timeout=180)
    content_type = response.headers.get("Content-Type", "").lower()
    content = response.content
    if pdf_bytes(content) or "application/pdf" in content_type:
        return {
            "content": content,
            "resolved_url": response.url,
            "source_content_type": content_type,
            "generated_pdf": False,
            "source_html": None,
            "source_state": source_headers(response.headers, response.url),
        }
    if "html" in content_type or b"<html" in content[:2048].lower():
        for candidate in html_document_candidates(response.url, content):
            if candidate in seen:
                continue
            try:
                resolved = resolve_public_document(
                    session, candidate, depth=depth + 1, seen=seen
                )
                if pdf_bytes(resolved["content"]):
                    resolved["source_html"] = content
                    return resolved
            except Exception:
                continue
        return {
            "content": content,
            "resolved_url": response.url,
            "source_content_type": content_type,
            "generated_pdf": True,
            "source_html": content,
            "source_state": source_headers(response.headers, response.url),
        }
    raise RuntimeError(
        f"Unsupported document response: {content_type or 'unknown content type'}"
    )


def create_text_snapshot_pdf(html: bytes, title: str, source_url: str) -> bytes:
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF is required to create a local PDF snapshot from an HTML viewer"
        )
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = normalize_space(soup.get_text("\n", strip=True))
    if not text:
        text = "The public eSCRIBE page did not expose readable document text."
    header = (
        f"Nanaimo Bylaw Tracker archival snapshot\n\n{title}\n\n"
        f"Source: {source_url}\n"
        f"Source content SHA-256: {sha256(html).hexdigest()}\n\n"
        "This PDF was generated from a publicly available eSCRIBE web page. "
        "It is not an original City of Nanaimo or eSCRIBE PDF.\n\n"
    )
    body = header + text
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    margin = 54
    rect = fitz.Rect(margin, margin, page.rect.width-margin, page.rect.height-margin)
    remaining = body
    while remaining:
        chars = min(len(remaining), 4200)
        chunk = remaining[:chars]
        written = page.insert_textbox(rect, chunk, fontsize=9, fontname="helv", lineheight=1.25)
        if written < 0 and chars > 500:
            remaining = remaining[:chars//2] + remaining[chars:]
            chunk = remaining[:chars//2]
            page.insert_textbox(rect, chunk, fontsize=9, fontname="helv", lineheight=1.2)
            remaining = remaining[len(chunk):]
        else:
            remaining = remaining[len(chunk):]
        if remaining:
            page = document.new_page(width=612, height=792)
            rect = fitz.Rect(margin, margin, page.rect.width-margin, page.rect.height-margin)
    document.set_metadata({
        "title": title,
        "author": "Nanaimo Bylaw Tracker",
        "subject": "Archival snapshot of a public eSCRIBE document page",
        "creator": "Nanaimo Bylaw Tracker",
        "producer": "Nanaimo Bylaw Tracker",
        "creationDate": "D:20000101000000Z",
        "modDate": "D:20000101000000Z",
    })
    # PyMuPDF otherwise creates a new trailer ID on every save. Suppressing it
    # makes identical HTML snapshots byte-identical and therefore deduplicable.
    data = document.tobytes(garbage=4, deflate=True, no_new_id=1)
    document.close()
    return data

def meeting_documents(session: requests.Session, meeting: dict[str, Any]) -> list[dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for url in meeting.get("documents", []):
        discovered[url] = {
            "title": Path(urlparse(url).path).name or "Document",
            "url": url,
            "document_type": classify_document("", url),
        }

    meeting_url = meeting.get("meeting_url")
    if meeting_url:
        try:
            soup = BeautifulSoup(source_get(session, meeting_url).text, "html.parser")
            page_text = normalize_space(soup.get_text(" ", strip=True))
            if not meeting.get("date"):
                meeting["date"] = parse_date(page_text)
            for anchor in soup.find_all("a", href=True):
                label = normalize_space(anchor.get_text(" ", strip=True))
                href = urljoin(meeting_url, anchor["href"])
                if not is_document_link(label, href):
                    continue
                title = label or Path(urlparse(href).path).name or "Document"
                if title.strip().lower() in {"html", "pdf", "view", "open"}:
                    title = classify_document(label, href).replace("-", " ").title()
                key = href.split("#", 1)[0]
                discovered[key] = {
                    "title": title,
                    "url": key,
                    "document_type": classify_document(label, href),
                }
        except Exception as exc:
            meeting["page_error"] = str(exc)

    return list(discovered.values())


def extract_pdf_text(path: Path) -> dict[str, Any]:
    return extract_pdf_text_with_ocr(
        path, enable_ocr=True, max_ocr_pages=6, max_pages=300, max_characters=MAX_PARSE_CHARS
    )


def council_document_paths(
    meeting: dict[str, Any],
    document: dict[str, Any],
    archive_run: Path,
) -> tuple[Path, Path]:
    date = meeting.get("date") or "undated"
    meeting_slug = slugify(f"{date}-{meeting.get('title', 'meeting')}")
    live_dir = COUNCIL_DIR / date / meeting_slug
    archive_dir = archive_run / date / meeting_slug
    base = slugify(document.get("title") or document["document_type"])
    filename = base if base.endswith(".pdf") else f"{base}.pdf"
    return live_dir / filename, archive_dir / filename


def council_archive_candidates(
    meeting: dict[str, Any],
    document: dict[str, Any],
    archive_index: PdfArchiveIndex,
) -> list[Path]:
    """Find archived copies by the deterministic meeting/document path.

    This allows reuse even when an older JSON record is missing, incomplete,
    or no longer points at the archived file.
    """
    date = meeting.get("date") or "undated"
    meeting_slug = slugify(f"{date}-{meeting.get('title', 'meeting')}")
    base = slugify(document.get("title") or document["document_type"])
    filename = base if base.endswith(".pdf") else f"{base}.pdf"
    return sorted(
        (
            path
            for path in archive_index.by_name.get(filename.lower(), [])
            if path.parent.name == meeting_slug
        ),
        reverse=True,
    )


def ensure_council_text(
    live_path: Path,
    archive_path: Path,
    previous: dict[str, Any] | None,
    *,
    force_extract: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Restore or extract a text sidecar without downloading the PDF again."""
    live_text_path = live_path.with_suffix(".txt")
    archive_text_path = archive_path.with_suffix(".txt")
    previous_text = existing_path(ROOT, previous.get("text_path") if previous else None)

    if not force_extract:
        cached_text = next((path for path in (previous_text, live_text_path) if path and path.is_file()), None)
        if cached_text:
            text = cached_text.read_text(encoding="utf-8", errors="replace")
            if text:
                live_text_path.parent.mkdir(parents=True, exist_ok=True)
                if cached_text != live_text_path:
                    live_text_path.write_text(text, encoding="utf-8")
                if not archive_text_path.is_file():
                    archive_text_path.parent.mkdir(parents=True, exist_ok=True)
                    archive_text_path.write_text(text, encoding="utf-8")
            return ({
                "text": text,
                "page_count": (previous or {}).get("page_count", 0),
                "error": (previous or {}).get("extraction_error"),
                "method": (previous or {}).get("text_extraction_method") or "cached",
                "ocr_pages": (previous or {}).get("ocr_pages") or [],
                "sparse_pages": (previous or {}).get("sparse_pages") or [],
                "ocr_error": (previous or {}).get("ocr_error"),
                "warnings": (previous or {}).get("text_extraction_warnings") or ["Reused existing extracted text"],
            }, cached_text != live_text_path)

    # This sidecar belongs to the selected archive PDF and is therefore safe
    # to restore even when previous/live text must be treated as stale.
    if archive_text_path.is_file():
        text = archive_text_path.read_text(encoding="utf-8", errors="replace")
        if text:
            live_text_path.parent.mkdir(parents=True, exist_ok=True)
            live_text_path.write_text(text, encoding="utf-8")
        return ({
            "text": text,
            "page_count": (previous or {}).get("page_count", 0),
            "error": (previous or {}).get("extraction_error"),
            "method": (previous or {}).get("text_extraction_method") or "cached-archive",
            "ocr_pages": (previous or {}).get("ocr_pages") or [],
            "sparse_pages": (previous or {}).get("sparse_pages") or [],
            "ocr_error": (previous or {}).get("ocr_error"),
            "warnings": ["Restored extracted text from the archive"],
        }, True)

    extraction = extract_pdf_text(live_path)
    text = extraction["text"]
    if text:
        live_text_path.parent.mkdir(parents=True, exist_ok=True)
        live_text_path.write_text(text, encoding="utf-8")
        archive_text_path.parent.mkdir(parents=True, exist_ok=True)
        archive_text_path.write_text(text, encoding="utf-8")
    return extraction, True


def reuse_document(
    session: requests.Session,
    meeting: dict[str, Any],
    document: dict[str, Any],
    cached: dict[str, Any] | None,
    archive_run: Path,
    archive_index: PdfArchiveIndex,
) -> tuple[dict[str, Any], str, str] | None:
    """Reuse an archived/local PDF and repair missing local files or text."""
    live_path, desired_archive_path = council_document_paths(meeting, document, archive_run)
    cached_hash = str((cached or {}).get("sha256") or "")
    hashed_archive = archive_index.by_hash.get(cached_hash) if cached_hash else None
    existing = archive_index.find_first([
        existing_path(ROOT, (cached or {}).get("archive_path")),
        hashed_archive,
        *council_archive_candidates(meeting, document, archive_index),
        existing_path(ROOT, (cached or {}).get("local_path")),
        live_path,
    ])
    if existing is None:
        return None

    source_state = probe_document_source(session, document["url"])
    is_original_pdf = str((cached or {}).get("archive_kind") or "original-pdf") == "original-pdf"
    if remote_state_changed(
        cached,
        source_state,
        local_size=existing.stat().st_size if is_original_pdf else None,
    ):
        return None

    digest, canonical_archive = archive_index.canonical_for_file(existing)
    action = "reused"
    if canonical_archive is None:
        stored = archive_index.ensure_file(existing, desired_archive_path)
        archive_path = stored.path
        action = "archive-repaired" if stored.created else "reused"
    else:
        archive_path = canonical_archive

    copy_if_needed(archive_path, live_path)
    extraction, text_repaired = ensure_council_text(live_path, archive_path, cached)

    record = {**(cached or {}), **document}
    record.update({
        "meeting_date": meeting.get("date") or "undated",
        "meeting_title": meeting.get("title"),
        "meeting_url": meeting.get("meeting_url"),
        "local_path": live_path.relative_to(ROOT).as_posix(),
        "archive_path": archive_path.relative_to(ROOT).as_posix(),
        "text_path": live_path.with_suffix(".txt").relative_to(ROOT).as_posix() if extraction["text"] else None,
        "sha256": digest,
        "size_bytes": live_path.stat().st_size,
        "page_count": extraction["page_count"],
        "extraction_error": extraction["error"],
        "text_extraction_method": extraction["method"],
        "ocr_pages": extraction["ocr_pages"],
        "sparse_pages": extraction["sparse_pages"],
        "ocr_error": extraction["ocr_error"],
        "text_extraction_warnings": extraction["warnings"],
        "checked_at": now_local().isoformat(timespec="seconds"),
        "archive_action": action,
        "text_repaired_from_local_pdf": bool(text_repaired),
    })
    for key, value in source_state.items():
        if value not in (None, ""):
            record[key] = value
    text = extraction["text"]
    return record, text, action


def download_document(
    session: requests.Session,
    meeting: dict[str, Any],
    document: dict[str, Any],
    archive_run: Path,
    archive_index: PdfArchiveIndex,
    previous: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Download only a new/proven-changed source and store unique PDF content."""
    live_path, desired_archive_path = council_document_paths(meeting, document, archive_run)
    live_path.parent.mkdir(parents=True, exist_ok=True)

    resolved = resolve_public_document(session, document["url"])
    if resolved["generated_pdf"]:
        pdf_content = create_text_snapshot_pdf(
            resolved["source_html"] or resolved["content"],
            document.get("title") or document["document_type"],
            document["url"],
        )
    else:
        pdf_content = resolved["content"]

    stored = archive_index.store_bytes(pdf_content, desired_archive_path)
    archive_path = stored.path
    previous_hash = str((previous or {}).get("sha256") or "")
    content_changed = previous_hash != stored.sha256
    copy_if_needed(archive_path, live_path)

    extraction, text_repaired = ensure_council_text(
        live_path, archive_path, previous, force_extract=content_changed
    )
    text = extraction["text"]

    source_html_path = None
    if resolved["generated_pdf"]:
        source_html_path = archive_path.with_suffix(".source.html")
        if not source_html_path.is_file():
            source_html_path.write_bytes(resolved["source_html"] or resolved["content"])

    if stored.created:
        action = "downloaded-changed" if previous_hash else "downloaded-new"
    else:
        action = "downloaded-deduplicated"

    result = {**(previous or {}), **document}
    result.update({
        "meeting_date": meeting.get("date") or "undated",
        "meeting_title": meeting.get("title"),
        "meeting_url": meeting.get("meeting_url"),
        "local_path": live_path.relative_to(ROOT).as_posix(),
        "archive_path": archive_path.relative_to(ROOT).as_posix(),
        "text_path": live_path.with_suffix(".txt").relative_to(ROOT).as_posix() if text else None,
        "sha256": stored.sha256,
        "size_bytes": live_path.stat().st_size,
        "page_count": extraction["page_count"],
        "extraction_error": extraction["error"],
        "text_extraction_method": extraction["method"],
        "ocr_pages": extraction["ocr_pages"],
        "sparse_pages": extraction["sparse_pages"],
        "ocr_error": extraction["ocr_error"],
        "text_extraction_warnings": extraction["warnings"],
        "retrieved_at": now_local().isoformat(timespec="seconds"),
        "checked_at": now_local().isoformat(timespec="seconds"),
        "resolved_url": resolved.get("resolved_url"),
        "generated_pdf": bool(resolved.get("generated_pdf")),
        "archive_kind": "generated-web-snapshot" if resolved.get("generated_pdf") else "original-pdf",
        "source_html_path": source_html_path.relative_to(ROOT).as_posix() if source_html_path else None,
        "archive_action": action,
        "text_repaired_from_local_pdf": bool(text_repaired),
    })
    # Persist validators for the original public URL so the next HEAD probe is
    # compared with the same endpoint, even when resolution followed an HTML
    # page to a separate PDF candidate.
    document_source_state = probe_document_source(session, document["url"]) or resolved.get("source_state")
    for key, value in document_source_state.items():
        if value not in (None, ""):
            result[key] = value
    if resolved.get("source_content_type") and not result.get("source_content_type"):
        result["source_content_type"] = resolved["source_content_type"]
    return result, text, action


def summary_links(session: requests.Session, years: list[int]) -> list[str]:
    try:
        soup = BeautifulSoup(source_get(session, SUMMARIES).text, "html.parser")
    except Exception as exc:
        print(f"Council summaries index failed: {exc}")
        return []

    links = []
    for anchor in soup.find_all("a", href=True):
        text = normalize_space(anchor.get_text(" ", strip=True))
        href = urljoin(SUMMARIES, anchor["href"])
        if "summary" not in f"{text} {href}".lower():
            continue
        date = parse_date(text)
        if date and years and int(date[:4]) not in years:
            continue
        if "/summaries/" in href and href.rstrip("/") != SUMMARIES.rstrip("/"):
            links.append(href)
    return list(dict.fromkeys(links))


def sentence_chunks(text: str) -> list[str]:
    """Create bounded chunks so malformed PDF text cannot stall regex parsing."""
    safe_text = (text or "")[:MAX_PARSE_CHARS]
    chunks: list[str] = []
    for raw_line in safe_text.splitlines():
        line = normalize_space(raw_line)
        if len(line) < 12:
            continue
        protected = re.sub(r"\b(No|Nos|St|Mt|Dr|Mr|Ms)\.", lambda match: match.group(0)[:-1] + "<DOT>", line, flags=re.I)
        parts = re.split(r"(?<=[.!?])\s+", protected)
        for part in parts:
            part = normalize_space(part.replace("<DOT>", "."))
            if not part:
                continue
            if len(part) <= MAX_CHUNK_CHARS:
                chunks.append(part)
                continue
            for offset in range(0, len(part), MAX_CHUNK_CHARS):
                bounded = part[offset:offset + MAX_CHUNK_CHARS].strip()
                if bounded:
                    chunks.append(bounded)
    return chunks


def clean_bylaw_title(chunk: str, number: str, match_start: int | None = None) -> str:
    if match_start is None:
        match = BYLAW_NUMBER_RE.search(chunk)
        match_start = match.start() if match else -1
    if match_start >= 0:
        prefix = chunk[max(0, match_start - 180):match_start]
        prefix = re.split(r"[.!?;]", prefix)[-1]
        prefix = normalize_space(prefix).strip('“”" :-–—')
        title = normalize_space(f"{prefix} Bylaw No. {number}").strip()
        if 10 <= len(title) <= 240:
            return title
    return f"Bylaw {number}"


def item_action(chunk: str) -> str:
    lower = chunk.lower()
    for term in ACTION_TERMS:
        if term in lower:
            if term == "reading":
                reading = re.search(r"\b(first|second|third|three)\s+readings?\b", lower)
                return reading.group(0).title() if reading else "Reading"
            return term.title()
    return "Discussed"


def extract_items(
    text: str,
    meeting: dict[str, Any],
    source_document: dict[str, Any] | None,
    bylaws: dict[str, dict[str, Any]],
    source_kind: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    chunks = sentence_chunks(text)

    for chunk in chunks:
        if "bylaw" not in chunk.lower():
            matches = ()
        else:
            matches = BYLAW_NUMBER_RE.finditer(chunk)
        for match in matches:
            number = match.group("number")
            base_number = number.split(".", 1)[0]
            matched = bylaws.get(number) or bylaws.get(base_number)
            title = clean_bylaw_title(chunk, number, match.start())
            if matched and title.lower() in {f"bylaw {number}".lower(), f"bylaw no. {number}".lower()}:
                title = matched.get("title") or title
            key = f"bylaw|{meeting.get('date')}|{number}|{item_action(chunk)}"
            if key in seen:
                continue
            seen.add(key)
            relationships = infer_relationships(number, chunk)
            items.append({
                "id": sha256(key.encode()).hexdigest()[:16],
                "date": meeting.get("date"),
                "meeting_title": meeting.get("title"),
                "meeting_group": meeting.get("meeting_group") or classify_meeting(str(meeting.get("title") or ""))[1],
                "meeting_url": meeting.get("meeting_url"),
                "type": "Bylaw",
                "number": number,
                "base_number": base_number,
                "relationships": relationships,
                "relationship_targets": relationship_targets(relationships),
                "title": title,
                "action": item_action(chunk),
                "summary": chunk[:700],
                "category": matched.get("category") if matched else None,
                "department": matched.get("department") if matched else None,
                "matched_bylaw": bool(matched),
                "bylaw_detail_url": f"bylaws/detail.html?number={base_number}" if matched else None,
                "source_kind": source_kind,
                "source_document_url": source_document.get("url") if source_document else meeting.get("summary_url"),
                "local_document": source_document.get("local_path") if source_document else None,
                "source_text": source_document.get("text_path") if source_document else None,
            })

        lower = chunk.lower()
        if any(chunk.startswith(prefix) for prefix in MOTION_PREFIXES) and "bylaw" not in lower:
            key = f"motion|{meeting.get('date')}|{chunk.lower()}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "id": sha256(key.encode()).hexdigest()[:16],
                "date": meeting.get("date"),
                "meeting_title": meeting.get("title"),
                "meeting_group": meeting.get("meeting_group") or classify_meeting(str(meeting.get("title") or ""))[1],
                "meeting_url": meeting.get("meeting_url"),
                "type": "Motion",
                "number": None,
                "base_number": None,
                "title": chunk[:180],
                "action": item_action(chunk),
                "summary": chunk[:700],
                "category": None,
                "department": None,
                "matched_bylaw": False,
                "bylaw_detail_url": None,
                "source_kind": source_kind,
                "source_document_url": source_document.get("url") if source_document else meeting.get("summary_url"),
                "local_document": source_document.get("local_path") if source_document else None,
                "source_text": source_document.get("text_path") if source_document else None,
            })
    return items


def collect_summary_items(
    session: requests.Session,
    years: list[int],
    bylaws: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries = []
    items = []
    for url in summary_links(session, years):
        try:
            response = source_get(session, url)
            soup = BeautifulSoup(response.text, "html.parser")
            title = normalize_space((soup.find("h1") or soup.title).get_text(" ", strip=True))
            text = soup.get_text("\n", strip=True)
            date = parse_date(title) or parse_date(text)
            summary_title = title.replace(" Summary", "") if title else "Council meeting"
            summary_title, summary_group = classify_meeting(summary_title)
            meeting = {
                "date": date,
                "title": summary_title,
                "meeting_group": summary_group,
                "meeting_url": url,
                "summary_url": url,
            }
            summaries.append({
                "date": date,
                "title": title,
                "url": url,
                "text": normalize_space(text)[:5000],
            })
            items.extend(extract_items(text, meeting, None, bylaws, "Council summary"))
            time.sleep(0.15)
        except Exception as exc:
            print(f"Summary failed: {url}: {exc}")
    return summaries, items


def deduplicate_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = {"Council summary": 3, "minutes": 2, "revised-agenda": 1, "agenda": 0}
    chosen: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = (
            item.get("date"),
            item.get("type"),
            item.get("number") or re.sub(r"\W+", " ", item.get("title", "").lower())[:120],
            item.get("action"),
        )
        key = json.dumps(identity, sort_keys=True)
        previous = chosen.get(key)
        current_rank = ranked.get(item.get("source_kind", ""), 0)
        previous_rank = ranked.get(previous.get("source_kind", ""), -1) if previous else -1
        if not previous or current_rank >= previous_rank:
            chosen[key] = item
    return sorted(
        chosen.values(),
        key=lambda item: (item.get("date") or "", item.get("type") or "", item.get("number") or ""),
        reverse=True,
    )



def choose_featured_item(
    items: list[dict[str, Any]],
    bylaws: dict[str, dict[str, Any]],
    generated_at: str,
) -> dict[str, Any] | None:
    """Choose the newest matched bylaw matter for the featured page.

    Active discussion stages rank ahead of completed adoption when events share
    the same date. The result remains evidence-based and links to official or
    locally archived Council sources.
    """
    action_priority = {
        "Deferred": 90,
        "Referred": 85,
        "Amended": 80,
        "Rescinded": 78,
        "First Reading": 75,
        "Second Reading": 74,
        "Third Reading": 73,
        "Three Readings": 72,
        "Reading": 70,
        "Discussed": 65,
        "Approved": 60,
        "Endorsed": 58,
        "Adopted": 45,
        "Passed": 40,
        "Received": 30,
    }
    candidates = [
        item for item in items
        if item.get("type") == "Bylaw" and (item.get("number") or item.get("base_number"))
    ]
    if not candidates:
        return None

    def rank(item: dict[str, Any]) -> tuple[str, int, int]:
        number = str(item.get("base_number") or item.get("number") or "")
        return (
            str(item.get("date") or ""),
            action_priority.get(str(item.get("action") or ""), 50),
            int(re.sub(r"\D", "", number) or 0),
        )

    item = max(candidates, key=rank)
    number = str(item.get("base_number") or item.get("number") or "")
    record = bylaws.get(str(item.get("number") or "")) or bylaws.get(number) or {}
    action = str(item.get("action") or "Council discussion")
    title = item.get("title") or record.get("title") or f"Bylaw {number}"
    source_url = (
        item.get("source_document_url")
        or item.get("meeting_url")
        or CITY_MEETINGS
    )
    official_bylaw = (
        record.get("pdf_url")
        or record.get("official_pdf")
        or record.get("source_url")
        or f"https://www.nanaimo.ca/bylaws/ViewBylaw/{number}.pdf"
    )
    status = action if action != "Discussed" else "Council discussion"
    return {
        "generated_at": generated_at,
        "timezone": "America/Vancouver",
        "automatically_selected": True,
        "selection_rule": "Newest collected Council bylaw item; active discussion actions rank ahead of completed actions on the same date.",
        "title": title,
        "base_bylaw_number": number,
        "status": status,
        "stage": action,
        "notice_date": item.get("date"),
        "department": item.get("department") or record.get("department") or "Not identified",
        "category": item.get("category") or record.get("category"),
        "summary": item.get("summary") or record.get("description") or "This bylaw was identified in the latest collected Council records.",
        "official_bylaw": official_bylaw,
        "official_notice": source_url,
        "council_documents": item.get("meeting_url") or CITY_MEETINGS,
        "local_document": item.get("local_document"),
        "source_kind": item.get("source_kind"),
        "source": "City of Nanaimo",
        "last_checked": generated_at[:10],
    }

def compare_document_sets(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    old = {item.get("url"): item for item in previous if item.get("url")}
    new = {item.get("url"): item for item in current if item.get("url")}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = []
    for key in old.keys() & new.keys():
        if old[key].get("sha256") and new[key].get("sha256") and old[key]["sha256"] != new[key]["sha256"]:
            changed.append(key)
    return {"added": added, "removed": removed, "changed": changed}



class CouncilProgress:
    """Dependency-free terminal progress bar for Council collection stages."""

    def __init__(self, total: int, stage: str) -> None:
        self.total = max(int(total), 1)
        self.stage = stage
        self.started = time.monotonic()
        self.failures = 0
        self.interactive = bool(getattr(sys.stdout, "isatty", lambda: False)())

    def update(self, current: int, detail: str = "", failures: int | None = None) -> None:
        current = max(0, min(int(current), self.total))
        if failures is not None:
            self.failures = max(0, int(failures))

        elapsed = max(time.monotonic() - self.started, 0.001)
        rate = current / elapsed if current else 0.0
        eta = (self.total - current) / rate if rate > 0 else 0.0
        percent = current / self.total * 100
        width = 26
        filled = min(width, round(width * current / self.total))
        bar = "#" * filled + "-" * (width - filled)

        line = (
            f"{self.stage:<11} [{bar}] {current:>3}/{self.total:<3} "
            f"{percent:6.1f}% | {detail:<26.26} "
            f"| failures {self.failures} "
            f"| elapsed {self._clock(elapsed)} | ETA {self._clock(eta)}"
        )
        if self.interactive:
            print("\r" + line, end="", flush=True)
        else:
            print(line, flush=True)

    def note(self, message: str) -> None:
        if self.interactive:
            print()
        print(message, flush=True)

    def finish(self, detail: str = "Complete") -> None:
        self.update(self.total, detail, self.failures)
        if self.interactive:
            print()

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(round(seconds)))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

def collect(download: bool, years: list[int]) -> None:
    run_time = now_local()
    generated_at = run_time.isoformat(timespec="seconds")
    run_dir = ARCHIVE_DIR / run_time.strftime("%Y-%m-%d") / run_time.strftime("%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "NanaimoBylawTracker/0.4 (+independent civic archive)",
        "Accept-Language": "en-CA,en;q=0.9",
    })

    bylaws = bylaw_lookup()
    discovered_meetings = discover_escribe_meetings(session, years)
    meeting_map: dict[str, dict[str, Any]] = {}
    for meeting in discovered_meetings:
        key = canonical_url(meeting.get("meeting_url")) or f"{meeting.get('date')}|{meeting.get('title')}"
        meeting_map.setdefault(key, meeting)
    meetings = list(meeting_map.values())

    resume = load_resume_state(years, download)
    documents: list[dict[str, Any]] = list(resume.get("documents") or [])
    extracted_items: list[dict[str, Any]] = list(resume.get("items") or [])
    processed_urls = {canonical_url(record.get("url")) for record in documents if record.get("url")}

    previous_payload = read_json(DOCUMENTS_JSON, {})
    previous_records = previous_payload if isinstance(previous_payload, list) else previous_payload.get("documents", [])
    previous_by_url = load_historical_documents()
    archive_index = PdfArchiveIndex(ROOT / "archive")
    archive_actions: dict[str, int] = {}
    text_repairs = 0
    queued_map: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    meeting_progress = CouncilProgress(len(meetings), "Meetings")
    meeting_progress.update(0, "Starting discovery")
    discovery_failures = 0

    for meeting_index, meeting in enumerate(meetings, start=1):
        try:
            docs = meeting_documents(session, meeting)
        except Exception as exc:
            docs = []
            discovery_failures += 1
            meeting["discovery_error"] = str(exc)
            meeting_progress.note(
                f"Meeting discovery failed: {meeting.get('meeting_url')}: {exc}"
            )

        meeting["document_count"] = len(docs)
        meeting["document_urls"] = [doc["url"] for doc in docs]
        for doc in docs:
            key = canonical_url(doc.get("url"))
            if key and key not in queued_map:
                queued_map[key] = (meeting, doc)
        meeting_progress.update(
            meeting_index,
            str(meeting.get("date") or meeting.get("title") or "Council meeting"),
            discovery_failures,
        )

    queued_documents = list(queued_map.values())
    meeting_progress.finish(f"{len(queued_documents)} unique documents found")

    document_progress = CouncilProgress(len(queued_documents), "Documents")
    document_progress.update(
        0,
        "Downloading" if download else "Indexing",
    )
    document_failures = 0

    for document_index, (meeting, doc) in enumerate(queued_documents, start=1):
        url_key = canonical_url(doc.get("url"))
        if url_key in processed_urls:
            document_progress.update(document_index, f"Cached: {doc.get('title') or 'Document'}", document_failures)
            continue

        record = {
            **doc,
            "meeting_date": meeting.get("date"),
            "meeting_title": meeting.get("title"),
            "meeting_url": meeting.get("meeting_url"),
        }
        cached = previous_by_url.get(url_key)

        if download:
            try:
                reused = reuse_document(
                    session, meeting, doc, cached, run_dir, archive_index
                )
                if reused is not None:
                    record, text, action = reused
                else:
                    record, text, action = download_document(
                        session, meeting, doc, run_dir, archive_index, cached
                    )
                    time.sleep(0.05)
                archive_actions[action] = archive_actions.get(action, 0) + 1
                if record.get("text_repaired_from_local_pdf"):
                    text_repairs += 1
                if text:
                    extracted_items.extend(extract_items(
                        text, meeting, record, bylaws, record.get("document_type") or "document"
                    ))
            except Exception as exc:
                document_failures += 1
                record["download_error"] = str(exc)
                if cached:
                    record = {**cached, **record}
                document_progress.note(f"Document failed: {doc['url']}: {exc}")
        elif cached:
            record = {**cached, **record}

        documents.append(record)
        processed_urls.add(url_key)
        if document_index % 10 == 0:
            save_resume_state(years, download, documents, deduplicate_items(extracted_items))
        document_progress.update(
            document_index,
            str(doc.get("title") or doc.get("document_type") or doc.get("url") or "Document"),
            document_failures,
        )

    document_progress.finish(
        f"{len(documents)} indexed; {document_failures} failed"
    )

    summaries, summary_items = collect_summary_items(session, years, bylaws)
    items = deduplicate_items([*extracted_items, *summary_items])

    # Homepage list: newest confirmed summary items first, then PDF-derived items.
    discussions = []
    for item in items[:40]:
        discussions.append({
            "date": item.get("date"),
            "type": item.get("type"),
            "number": item.get("number"),
            "title": item.get("title"),
            "action": item.get("action"),
            "summary": item.get("summary"),
            "url": item.get("bylaw_detail_url") or item.get("local_document") or item.get("source_document_url") or item.get("meeting_url"),
            "meeting_url": item.get("meeting_url"),
            "meeting_group": item.get("meeting_group"),
            "source_kind": item.get("source_kind"),
        })

    previous_documents_payload = read_json(DOCUMENTS_JSON, {})
    previous_documents = (
        previous_documents_payload if isinstance(previous_documents_payload, list)
        else previous_documents_payload.get("documents", [])
    )
    changes = compare_document_sets(previous_documents, documents)

    metadata = {
        "generated_at": generated_at,
        "timezone": "America/Vancouver",
        "years": years,
        "official_meeting_page": CITY_MEETINGS,
        "escribe_source": ESCRIBE,
        "summaries_source": SUMMARIES,
        "downloaded_pdfs": download,
        "pdf_archive_actions": archive_actions,
        "pdf_text_repairs": text_repairs,
        "preexisting_duplicate_archive_files_detected": archive_index.duplicate_file_count,
        "archive_policy": "Reuse archived PDFs; download only new or proven-changed PDF sources; store unique SHA-256 content only.",
    }
    meetings_payload = {"metadata": metadata, "meetings": meetings}
    documents_payload = {"metadata": metadata, "documents": documents}
    items_payload = {"metadata": metadata, "summaries": summaries, "items": items}
    committee_items = [item for item in items if str(item.get("meeting_group") or "").lower() in {"committee", "board", "commission", "panel"}]
    committee_counts = {}
    for item in committee_items:
        name = normalize_space(item.get("meeting_title") or item.get("committee_name") or "Committee, board or panel")
        entry = committee_counts.setdefault(name, {"name": name, "count": 0, "latest_date": None})
        entry["count"] += 1
        date = item.get("date")
        if date and (not entry["latest_date"] or date > entry["latest_date"]):
            entry["latest_date"] = date
    committee_payload = {"metadata": metadata, "count": len(committee_items), "items": committee_items}
    committee_index_payload = {"metadata": metadata, "count": len(committee_counts), "committees": sorted(committee_counts.values(), key=lambda value: value["name"].lower())}
    discussions_payload = {
        "metadata": metadata,
        "count": len(discussions),
        "items": discussions,
    }
    featured_payload = choose_featured_item(items, bylaws, generated_at)

    write_json(MEETINGS_JSON, meetings_payload)
    write_json(DOCUMENTS_JSON, documents_payload)
    write_json(ITEMS_JSON, items_payload)
    write_json(COMMITTEE_ITEMS_JSON, committee_payload)
    write_json(COMMITTEE_INDEX_JSON, committee_index_payload)
    write_json(DISCUSSIONS_JSON, discussions_payload)
    if featured_payload:
        write_json(FEATURED_JSON, featured_payload)
    write_json(run_dir / "council-meetings.json", meetings_payload)
    write_json(run_dir / "council-documents.json", documents_payload)
    write_json(run_dir / "council-items.json", items_payload)
    write_json(run_dir / "committee-items.json", committee_payload)
    write_json(run_dir / "committee-index.json", committee_index_payload)
    write_json(run_dir / "council-discussions.json", discussions_payload)
    if featured_payload:
        write_json(run_dir / "featured.json", featured_payload)
    write_json(run_dir / "changes.json", changes)

    log = read_json(CHANGE_LOG, {"timezone": "America/Vancouver", "runs": []})
    log["last_updated"] = generated_at
    log.setdefault("runs", []).append({
        "generated_at": generated_at,
        "snapshot": run_dir.relative_to(ROOT).as_posix(),
        "meetings": len(meetings),
        "documents": len(documents),
        "items": len(items),
        "added_documents": len(changes["added"]),
        "changed_documents": len(changes["changed"]),
        "removed_documents": len(changes["removed"]),
    })
    write_json(CHANGE_LOG, log)

    print(f"Wrote {len(meetings)} meetings to {MEETINGS_JSON}")
    print(f"Wrote {len(documents)} documents to {DOCUMENTS_JSON}")
    if download:
        print("PDF archive actions: " + ", ".join(f"{key}={value}" for key, value in sorted(archive_actions.items())))
        print(f"Text sidecars repaired from local PDFs: {text_repairs}")
        if archive_index.duplicate_file_count:
            print(f"Warning: detected {archive_index.duplicate_file_count} pre-existing duplicate archive PDFs; no new duplicate PDF was written.")
    print(f"Wrote {len(items)} extracted civic meeting items to {ITEMS_JSON}")
    print(f"Wrote {len(committee_items)} committee items to {COMMITTEE_ITEMS_JSON}")
    print(f"Wrote {len(committee_counts)} committee directory entries to {COMMITTEE_INDEX_JSON}")
    print(f"Wrote {min(40, len(discussions))} homepage discussion records to {DISCUSSIONS_JSON}")
    if featured_payload:
        print(f"Selected featured bylaw {featured_payload['base_bylaw_number']} from the newest Council activity")
    print(f"Archived run at {run_dir}")
    PROGRESS_JSON.unlink(missing_ok=True)

    verifier = ROOT / "tools" / "verify_council_collection.py"
    verification = subprocess.run(
        [sys.executable, str(verifier)],
        cwd=ROOT,
        check=False,
    )
    if verification.returncode != 0:
        raise SystemExit(
            "Council collection finished, but verification reported a critical failure. "
            "See data/council-verification.json."
        )


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Download and archive PDFs; reuse existing local PDFs and extracted text when available.")
    parser.add_argument(
        "--years", nargs="+", type=int,
        default=[now_local().year, now_local().year - 1],
        help="Meeting years to collect; defaults to current and previous year.",
    )
    args = parser.parse_args()
    collect(args.download, sorted(set(args.years), reverse=True))
