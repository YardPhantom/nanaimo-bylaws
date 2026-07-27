#!/usr/bin/env python3
"""Verify every authored HTML page uses the same shared header component."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.13.1"
EXCLUDED_PARTS = {"archive", "runtime", "bylaws/pdf"}


def is_authored_page(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return not any(rel == part or rel.startswith(part + "/") for part in EXCLUDED_PARTS)


def expected_root(path: Path) -> str:
    return ".." if len(path.relative_to(ROOT).parts) > 1 else "."


def main() -> int:
    errors: list[str] = []
    pages = [p for p in sorted(ROOT.rglob("*.html")) if is_authored_page(p)]
    total = len(pages)
    for index, page in enumerate(pages, start=1):
        width = 26
        filled = round(width * index / max(total, 1))
        bar = "#" * filled + "-" * (width - filled)
        rel = page.relative_to(ROOT).as_posix()
        print(f"\rHeaders     [{bar}] {index:>3}/{total:<3} {index / max(total, 1) * 100:6.1f}% | {rel:<42}", end="", flush=True)
        text = page.read_text(encoding="utf-8")
        placeholders = re.findall(r'<div\s+[^>]*data-shared-header(?:="")?[^>]*></div>', text, re.I)
        scripts = re.findall(r'<script\b[^>]*src="([^"]*shared-header\.min\.js\?v=[^"]+)"[^>]*></script>', text, re.I)
        if len(placeholders) != 1:
            errors.append(f"{rel}: expected one shared-header placeholder, found {len(placeholders)}")
        else:
            root = expected_root(page)
            if f'data-root="{root}"' not in placeholders[0]:
                errors.append(f"{rel}: shared-header data-root must be {root!r}")
        if len(scripts) != 1:
            errors.append(f"{rel}: expected one shared-header script, found {len(scripts)}")
        else:
            root = expected_root(page)
            expected = ("../" if root == ".." else "") + f"shared-header.min.js?v={VERSION}"
            if scripts[0] != expected:
                errors.append(f"{rel}: header script is {scripts[0]!r}, expected {expected!r}")
        if placeholders and scripts:
            if text.find(placeholders[0]) > text.find(scripts[0]):
                errors.append(f"{rel}: header script appears before its placeholder")
        if '<header class="site-header' in text:
            errors.append(f"{rel}: contains a hard-coded site header instead of shared component")
    if pages:
        print()
    if errors:
        print("Shared header verification FAILED")
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(f"Shared header verification PASS: {len(pages)} authored pages use V{VERSION} shared header.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
