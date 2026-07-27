#!/usr/bin/env python3
"""Pull and publish Nanaimo Bylaw Tracker runtime data using Cloudflare R2.

Required environment variables:
  CLOUDFLARE_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET_NAME

The collector uses the downloaded R2 state exactly as it previously used local IIS
state. Publishing is content-aware: unchanged files are skipped and archives are
never deleted by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
VERSION = "V0.13.1"
STATE_PREFIXES = ("data/", "archive/", "bylaws/pdf/", "council/")
DATA_GLOBS = ("data/*.json",)
ARCHIVE_GLOBS = ("archive/**/*", "bylaws/pdf/**/*", "council/**/*")
EXCLUDED_NAMES = {
    "index.html", "list.js", "detail.html", "detail.js", "web.config",
    ".gitkeep", "desktop.ini", "thumbs.db"
}
EXCLUDED_SUFFIXES = {".pyc", ".tmp", ".log", ".db", ".sqlite", ".sqlite3"}


@dataclass(frozen=True)
class Settings:
    account_id: str
    access_key: str
    secret_key: str
    bucket: str

    @property
    def endpoint(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def settings_from_env() -> Settings:
    values = {
        "account_id": os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        "access_key": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "secret_key": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket": os.getenv("R2_BUCKET_NAME", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SystemExit("Missing R2 environment variables: " + ", ".join(missing))
    return Settings(**values)


def client_for(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 8, "mode": "standard"}),
    )


def safe_target(key: str) -> Path:
    normalized = key.replace("\\", "/").lstrip("/")
    parts = Path(normalized).parts
    if not normalized or ".." in parts:
        raise ValueError(f"Unsafe R2 object key: {key!r}")
    target = (ROOT / normalized).resolve()
    if ROOT.resolve() not in target.parents:
        raise ValueError(f"Object key escapes project root: {key!r}")
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_publish(path: Path) -> bool:
    if not path.is_file() or path.name.lower() in EXCLUDED_NAMES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    relative = path.relative_to(ROOT).as_posix()
    if relative.startswith("council/") and path.parent == ROOT / "council":
        return False
    return relative.startswith(("data/", "archive/", "bylaws/pdf/", "council/"))


def local_runtime_files() -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in (*DATA_GLOBS, *ARCHIVE_GLOBS):
        for path in ROOT.glob(pattern):
            if should_publish(path):
                found[path.relative_to(ROOT).as_posix()] = path
    return [found[key] for key in sorted(found)]


def list_objects(s3, bucket: str, prefix: str) -> Iterable[dict]:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


def pull(settings: Settings) -> None:
    s3 = client_for(settings)
    downloaded = skipped = 0
    for prefix in STATE_PREFIXES:
        for item in list_objects(s3, settings.bucket, prefix):
            key = item["Key"]
            if key.endswith("/"):
                continue
            target = safe_target(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            remote_size = int(item.get("Size", 0))
            if target.exists() and target.stat().st_size == remote_size:
                metadata = s3.head_object(Bucket=settings.bucket, Key=key).get("Metadata", {})
                remote_hash = metadata.get("sha256")
                if remote_hash and sha256_file(target) == remote_hash:
                    skipped += 1
                    continue
            temporary = target.with_suffix(target.suffix + ".r2-download")
            s3.download_file(settings.bucket, key, str(temporary))
            temporary.replace(target)
            downloaded += 1
    print(f"R2 pull complete: {downloaded} downloaded, {skipped} unchanged.")


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed:
        return guessed
    if path.suffix.lower() == ".json":
        return "application/json"
    return "application/octet-stream"


def cache_control(path: Path) -> str:
    relative = path.relative_to(ROOT).as_posix()
    if relative.startswith("data/"):
        return "public, max-age=60, must-revalidate"
    if path.suffix.lower() in {".pdf", ".txt"}:
        return "public, max-age=3600"
    return "public, max-age=300, must-revalidate"


def remote_sha256(s3, bucket: str, key: str) -> str:
    try:
        response = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return ""
        raise
    return response.get("Metadata", {}).get("sha256", "")


def upload_file(s3, settings: Settings, path: Path, key: str, digest: str) -> bool:
    if remote_sha256(s3, settings.bucket, key) == digest:
        return False
    s3.upload_file(
        str(path),
        settings.bucket,
        key,
        ExtraArgs={
            "ContentType": content_type(path),
            "CacheControl": cache_control(path),
            "Metadata": {"sha256": digest, "source": "nanaimo-bylaw-tracker"},
        },
    )
    return True


def rows_from(path: Path, key: str) -> list:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return payload
    rows = payload.get(key, []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def build_manifest(files: list[Path], digests: dict[str, str]) -> dict:
    pdfs = []
    total_bytes = 0
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        size = path.stat().st_size
        total_bytes += size
        if path.suffix.lower() == ".pdf":
            pdfs.append({"key": relative, "sha256": digests[relative], "bytes": size})
    pdfs.sort(key=lambda item: item["key"])
    archive_pdfs = [item for item in pdfs if item["key"].startswith("archive/")]
    unique_archive_hashes = len({item["sha256"] for item in archive_pdfs})
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectVersion": VERSION,
        "objectCount": len(files),
        "totalBytes": total_bytes,
        "pdfCount": len(pdfs),
        "archivePdfCount": len(archive_pdfs),
        "uniqueArchivePdfHashes": unique_archive_hashes,
        "duplicateArchivePdfHashes": len(archive_pdfs) - unique_archive_hashes,
        "pdfs": pdfs,
    }


def build_status(manifest: dict, upload_counts: dict) -> dict:
    bylaws = rows_from(ROOT / "data" / "bylaws.json", "bylaws")
    meetings = rows_from(ROOT / "data" / "council-meetings.json", "meetings")
    documents = rows_from(ROOT / "data" / "council-documents.json", "documents")
    items = rows_from(ROOT / "data" / "council-items.json", "items")
    committee_items = rows_from(ROOT / "data" / "committee-items.json", "items")
    return {
        "schemaVersion": 1,
        "status": "ok",
        "storage": "Cloudflare R2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectVersion": VERSION,
        "githubRunId": os.getenv("GITHUB_RUN_ID") or None,
        "githubRunAttempt": os.getenv("GITHUB_RUN_ATTEMPT") or None,
        "counts": {
            "bylaws": len(bylaws),
            "councilMeetings": len(meetings),
            "councilDocuments": len(documents),
            "councilItems": len(items),
            "committeeItems": len(committee_items),
            "archivePdfs": manifest["archivePdfCount"],
            "uniqueArchivePdfHashes": manifest["uniqueArchivePdfHashes"],
            "duplicateArchivePdfHashes": manifest["duplicateArchivePdfHashes"],
        },
        "publish": upload_counts,
        "directoryListing": False,
    }


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def publish(settings: Settings) -> None:
    s3 = client_for(settings)
    files = local_runtime_files()
    if not (ROOT / "data" / "bylaws.json").exists():
        raise SystemExit("data/bylaws.json is missing; refusing to publish an incomplete cloud dataset.")

    digests = {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in files}
    manifest = build_manifest(files, digests)
    if manifest["duplicateArchivePdfHashes"]:
        raise SystemExit(
            f"Refusing to publish: {manifest['duplicateArchivePdfHashes']} duplicate PDF hash(es) remain inside archive/. "
            "Run tools/deduplicate_archive.py --apply first."
        )

    manifest_path = ROOT / "archive-manifest.json"
    write_json(manifest_path, manifest)
    files.append(manifest_path)
    digests["archive-manifest.json"] = sha256_file(manifest_path)

    uploaded = unchanged = 0
    for path in files:
        key = path.relative_to(ROOT).as_posix()
        if upload_file(s3, settings, path, key, digests[key]):
            uploaded += 1
            print(f"Uploaded {key}")
        else:
            unchanged += 1

    status = build_status(manifest, {"uploaded": uploaded, "unchanged": unchanged})
    status_path = ROOT / "collection-status.json"
    write_json(status_path, status)
    status_hash = sha256_file(status_path)
    if upload_file(s3, settings, status_path, "collection-status.json", status_hash):
        uploaded += 1
        print("Uploaded collection-status.json")
    else:
        unchanged += 1

    print(f"R2 publish complete: {uploaded} uploaded, {unchanged} unchanged.")


def verify(settings: Settings) -> None:
    s3 = client_for(settings)
    required = [
        "data/bylaws.json",
        "data/council-items.json",
        "data/committee-items.json",
        "archive-manifest.json",
        "collection-status.json",
    ]
    failures = []
    for key in required:
        try:
            response = s3.head_object(Bucket=settings.bucket, Key=key)
            print(f"OK {key} ({response.get('ContentLength', 0)} bytes)")
        except ClientError as error:
            failures.append(f"{key}: {error.response.get('Error', {}).get('Code', 'error')}")
    if failures:
        raise SystemExit("R2 verification failed:\n- " + "\n- ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pull", "publish", "verify"))
    args = parser.parse_args()
    settings = settings_from_env()
    {"pull": pull, "publish": publish, "verify": verify}[args.command](settings)


if __name__ == "__main__":
    main()
