#!/usr/bin/env python3
"""Run both Nanaimo collection pipelines."""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

def run(script: str, *args: str) -> None:
    command = [sys.executable, str(TOOLS / script), *args]
    print(">", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)

if __name__ == "__main__":
    run("deduplicate_archive.py", "--apply")
    run("collect_bylaws.py", "--download-pdfs")
    run("collect_council.py", "--download")
    run("deduplicate_archive.py", "--check")
