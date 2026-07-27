#!/usr/bin/env python3
"""PDF text extraction with selective OCR fallback.

Normal embedded-text extraction is always attempted first. OCR is used only
for pages whose extracted text is empty or too sparse to be useful.

Optional OCR requirements:
- PyMuPDF
- pytesseract
- Pillow
- Tesseract OCR installed on the machine

Set TESSERACT_CMD when tesseract.exe is not on PATH.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re
import shutil

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None


MIN_ALNUM_PER_PAGE = 80


def _alnum_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", text or ""))


def _configure_tesseract() -> str | None:
    if pytesseract is None:
        return "pytesseract is not installed"

    configured = os.environ.get("TESSERACT_CMD")
    candidates = [
        configured,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return None
    return "Tesseract OCR executable was not found; install it or set TESSERACT_CMD"


def extract_pdf_text(
    path: Path,
    *,
    enable_ocr: bool = True,
    language: str = "eng",
    min_alnum_per_page: int = MIN_ALNUM_PER_PAGE,
    dpi: int = 150,
    max_ocr_pages: int = 12,
    max_pages: int = 300,
    max_characters: int = 2_000_000,
) -> dict[str, Any]:
    page_texts: list[str] = []
    warnings: list[str] = []
    extraction_error: str | None = None

    # PyMuPDF is substantially more tolerant and faster for many eSCRIBE PDFs.
    # Use it first so malformed content streams cannot stall pypdf extraction.
    if fitz is not None:
        try:
            with fitz.open(path) as document:
                page_limit = min(document.page_count, max_pages)
                page_texts = [document.load_page(index).get_text("text") or "" for index in range(page_limit)]
                if document.page_count > max_pages:
                    warnings.append(f"Embedded extraction limited to {max_pages} of {document.page_count} pages")
        except Exception as exc:
            extraction_error = f"PyMuPDF extraction failed: {exc}"

    if not page_texts and PdfReader is not None:
        try:
            reader = PdfReader(str(path), strict=False)
            page_texts = []
            for page_number, page in enumerate(reader.pages[:max_pages], start=1):
                try:
                    page_texts.append(page.extract_text() or "")
                except Exception as exc:
                    page_texts.append("")
                    warnings.append(f"pypdf page {page_number}: {exc}")
        except Exception as exc:
            extraction_error = f"pypdf extraction failed: {exc}"

    if not page_texts and fitz is None and PdfReader is None:
        extraction_error = "Neither PyMuPDF nor pypdf is installed"

    sparse_pages = [
        index
        for index, text in enumerate(page_texts)
        if _alnum_count(text) < min_alnum_per_page
    ]
    ocr_pages: list[int] = []
    ocr_error: str | None = None

    if enable_ocr and sparse_pages:
        if fitz is None or pytesseract is None or Image is None:
            ocr_error = "OCR dependencies are unavailable; install PyMuPDF, pytesseract, and Pillow"
        else:
            ocr_error = _configure_tesseract()

        if ocr_error is None:
            try:
                scale = dpi / 72
                matrix = fitz.Matrix(scale, scale)
                with fitz.open(path) as document:
                    if not page_texts:
                        page_texts = [""] * document.page_count
                    ocr_candidates = sparse_pages[:max_ocr_pages]
                    if len(sparse_pages) > max_ocr_pages:
                        warnings.append(
                            f"OCR limited to {max_ocr_pages} of {len(sparse_pages)} sparse pages"
                        )
                    for index in ocr_candidates:
                        if index >= document.page_count:
                            continue
                        page = document.load_page(index)
                        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                        image = Image.frombytes(
                            "RGB",
                            (pixmap.width, pixmap.height),
                            pixmap.samples,
                        )
                        ocr_text = pytesseract.image_to_string(
                            image,
                            lang=language,
                            config="--psm 6",
                        )
                        if _alnum_count(ocr_text) > _alnum_count(page_texts[index]):
                            page_texts[index] = ocr_text
                            ocr_pages.append(index + 1)
            except Exception as exc:
                ocr_error = str(exc)

    combined = "\n\n".join(
        f"--- Page {index + 1} ---\n{text.strip()}"
        for index, text in enumerate(page_texts)
        if text.strip()
    )

    if len(combined) > max_characters:
        combined = combined[:max_characters]
        warnings.append(f"Extracted text limited to {max_characters} characters")

    if ocr_pages and len(ocr_pages) == len(page_texts):
        method = "ocr"
    elif ocr_pages:
        method = "hybrid"
    elif combined:
        method = "pypdf"
    else:
        method = "none"

    if extraction_error:
        warnings.append(f"Embedded text extraction: {extraction_error}")
    if ocr_error:
        warnings.append(f"OCR fallback: {ocr_error}")

    return {
        "text": combined,
        "page_count": len(page_texts),
        "method": method,
        "ocr_pages": ocr_pages,
        "sparse_pages": [index + 1 for index in sparse_pages],
        "error": extraction_error if not combined else None,
        "ocr_error": ocr_error,
        "warnings": warnings,
        "character_count": len(combined),
    }
