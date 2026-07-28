#!/usr/bin/env python3
"""Send Nanaimo Bylaw Tracker subscription alerts through Brevo SMTP.

The sender runs after the cloud collector. It reads the freshly collected local
JSON files in the GitHub Actions workspace, reads private subscription settings
with Firebase Admin, and records one-way-hashed delivery state in Firestore.

Production examples:
  python tools/send_subscription_updates.py
  python tools/send_subscription_updates.py --dry-run
  python tools/send_subscription_updates.py --test-recipient owner@example.com
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urljoin
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

try:
    import firebase_admin
    from firebase_admin import auth, credentials, firestore
except ImportError:  # Allows local syntax/unit checks before requirements are installed.
    firebase_admin = None
    auth = credentials = firestore = None

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "runtime" / "subscription.env", override=False)

TZ = ZoneInfo(os.environ.get("SUBSCRIPTION_TIMEZONE", "America/Vancouver"))
CHANGE_LOG = ROOT / "data" / "change-log.json"
COUNCIL_CHANGE_LOG = ROOT / "data" / "council-change-log.json"
STATUS_PATH = ROOT / "subscription-delivery-status.json"
ALLOWED_CHANGE_TYPES = {"new", "amended", "consolidated", "repealed"}
COMMITTEE_TERMS = (
    "committee",
    "board",
    "commission",
    "panel",
    "task force",
    "working group",
    "governance and priorities",
    "finance and audit",
)


@dataclass(frozen=True)
class AlertEvent:
    key: str
    change_type: str
    category: str
    title: str
    url: str
    occurred_at: datetime
    source: str


@dataclass
class RecipientGroup:
    recipient: str
    activation_at: datetime
    change_types: set[str]
    categories: set[str]
    all_categories: bool
    frequencies: set[str]
    uids: set[str]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_status(payload: dict[str, Any]) -> None:
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "timezone": str(TZ),
        **payload,
    }
    temporary = STATUS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATUS_PATH)


def bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def require_site_url() -> str:
    value = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if not value.lower().startswith(("https://", "http://")):
        raise RuntimeError("PUBLIC_SITE_URL must be the deployed Nanaimo Bylaw Tracker URL.")
    return value


def normalize_datetime(value: Any, *, date_only_hour: int = 12) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime_time(hour=date_only_hour), tzinfo=TZ)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text[:10])
            except ValueError:
                return None
            parsed = datetime.combine(parsed_date, datetime_time(hour=date_only_hour), tzinfo=TZ)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(timezone.utc)


def normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def email_state_id(email: str) -> str:
    return hashlib.sha256(normalized_email(email).encode("utf-8")).hexdigest()


def stable_hash(parts: Iterable[Any]) -> str:
    text = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def classify_change_type(value: Any) -> str:
    text = str(value or "").lower()
    if "repeal" in text or "replace" in text or "rescind" in text:
        return "repealed"
    if "consolidat" in text:
        return "consolidated"
    if "amend" in text or "reading" in text or text == "changed":
        return "amended"
    return "new"


def is_committee_item(item: dict[str, Any]) -> bool:
    explicit = str(item.get("meeting_group") or "").strip().lower()
    if explicit in {"committee", "board", "commission", "panel", "task-force", "working-group"}:
        return True
    if explicit in {"council", "public-hearing"}:
        return False
    title = " ".join(
        str(item.get(key) or "")
        for key in ("meeting_title", "committee_name", "title")
    ).lower()
    return any(term in title for term in COMMITTEE_TERMS)


def absolute_url(site_url: str, value: Any, fallback: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raw = fallback
    if raw.lower().startswith(("https://", "http://")):
        return raw
    return urljoin(site_url + "/", raw.lstrip("/"))


def bylaw_events(site_url: str) -> list[AlertEvent]:
    payload = read_json(CHANGE_LOG, {})
    rows = payload if isinstance(payload, list) else payload.get("events", [])
    events: list[AlertEvent] = []
    for item in rows if isinstance(rows, list) else []:
        if item.get("baseline") or str(item.get("change_type") or "").lower() == "baseline":
            continue
        occurred_at = normalize_datetime(item.get("date"))
        if not occurred_at:
            continue
        number = str(item.get("number") or "").strip()
        key = str(item.get("id") or "").strip() or "bylaw:" + stable_hash(
            (item.get("date"), item.get("change_type"), number, item.get("title"))
        )
        detail = item.get("detail_url") or f"bylaws/detail.html?number={quote(number)}"
        events.append(AlertEvent(
            key=f"bylaw:{key}",
            change_type=classify_change_type(item.get("status") or item.get("change_type")),
            category=str(item.get("category") or "Other").strip(),
            title=str(item.get("title") or f"Bylaw {number}").strip(),
            url=absolute_url(site_url, detail, "bylaws/index.html"),
            occurred_at=occurred_at,
            source="Bylaw archive",
        ))
    return events


def council_events(site_url: str) -> list[AlertEvent]:
    payload = read_json(COUNCIL_CHANGE_LOG, {})
    rows = payload if isinstance(payload, list) else payload.get("events", [])
    events: list[AlertEvent] = []
    for item in rows if isinstance(rows, list) else []:
        if item.get("baseline") or is_committee_item(item):
            continue
        occurred_at = normalize_datetime(item.get("date"))
        if not occurred_at:
            continue
        item_id = str(item.get("item_id") or "").strip() or stable_hash((
            item.get("meeting_date"), item.get("meeting_title"), item.get("type"),
            item.get("number"), item.get("action"), item.get("title"),
        ))
        event_id = str(item.get("id") or "").strip() or stable_hash((
            item.get("date"), item.get("change_type"), item_id,
        ))
        detail = item.get("bylaw_detail_url")
        if not detail:
            local_pdf = str(item.get("local_document") or "").strip().replace("\\", "/")
            if local_pdf and not local_pdf.lower().startswith(("http://", "https://")):
                detail = "pdf.html?" + urlencode({"file": local_pdf})
            else:
                detail = item.get("source_document_url") or item.get("meeting_url") or "council/index.html"
        title = item.get("title") or item.get("summary") or "Council item"
        events.append(AlertEvent(
            key=f"council:{event_id}",
            change_type=classify_change_type(item.get("action") or item.get("change_type")),
            category=str(item.get("category") or "Other").strip(),
            title=str(title).strip(),
            url=absolute_url(site_url, detail, "council/index.html"),
            occurred_at=occurred_at,
            source="Council activity",
        ))
    return events


def collected_events(site_url: str) -> list[AlertEvent]:
    unique: dict[str, AlertEvent] = {}
    for event in [*bylaw_events(site_url), *council_events(site_url)]:
        existing = unique.get(event.key)
        if not existing or event.occurred_at > existing.occurred_at:
            unique[event.key] = event
    return sorted(unique.values(), key=lambda event: event.occurred_at, reverse=True)


def firebase_credential_source():
    if credentials is None:
        raise RuntimeError("firebase-admin is not installed. Run pip install -r tools/requirements.txt.")
    encoded = os.environ.get("FIREBASE_SERVICE_ACCOUNT_BASE64", "").strip()
    if encoded:
        try:
            payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_BASE64 is not valid base64-encoded JSON.") from exc
        return credentials.Certificate(payload)

    raw_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw_json:
        try:
            return credentials.Certificate(json.loads(raw_json))
        except json.JSONDecodeError as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc

    account = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if account:
        path = Path(account)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            raise RuntimeError(f"Firebase service account not found: {path}")
        return credentials.Certificate(path)

    raise RuntimeError(
        "Configure FIREBASE_SERVICE_ACCOUNT_BASE64, FIREBASE_SERVICE_ACCOUNT_JSON, "
        "or FIREBASE_SERVICE_ACCOUNT."
    )


def init_firebase():
    if firebase_admin is None or firestore is None:
        raise RuntimeError("firebase-admin is not installed. Run pip install -r tools/requirements.txt.")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(firebase_credential_source())
    return firestore.client()


def validate_smtp() -> dict[str, Any]:
    required = ["SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"]
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Missing SMTP configuration: " + ", ".join(missing))
    return {
        "host": os.environ.get("SMTP_HOST", "smtp-relay.brevo.com").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": os.environ["SMTP_USERNAME"].strip(),
        "password": os.environ["SMTP_PASSWORD"],
        "sender": os.environ["SMTP_FROM"].strip(),
        "reply_to": os.environ.get("SMTP_REPLY_TO", "").strip(),
    }


def smtp_send(recipient: str, subject: str, text: str, html_body: str) -> None:
    config = validate_smtp()
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = recipient
    message["Subject"] = subject
    if config["reply_to"]:
        message["Reply-To"] = config["reply_to"]
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    if config["port"] == 465:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=30, context=context) as client:
            client.login(config["username"], config["password"])
            client.send_message(message)
        return
    with smtplib.SMTP(config["host"], config["port"], timeout=30) as client:
        client.ehlo()
        client.starttls(context=context)
        client.ehlo()
        client.login(config["username"], config["password"])
        client.send_message(message)


def subscription_activation(snapshot, settings: dict[str, Any]) -> datetime:
    candidates = [
        normalize_datetime(settings.get("activatedAt")),
        normalize_datetime(settings.get("createdAt")),
        normalize_datetime(getattr(snapshot, "create_time", None)),
        normalize_datetime(settings.get("updatedAt")),
    ]
    return next((value for value in candidates if value), datetime.now(timezone.utc))


def load_recipient_groups(db) -> tuple[dict[str, RecipientGroup], int, int]:
    groups: dict[str, RecipientGroup] = {}
    active_documents = 0
    duplicates = 0
    for snapshot in db.collection_group("subscriptions").stream():
        if snapshot.id != "email":
            continue
        settings = snapshot.to_dict() or {}
        if not settings.get("active"):
            continue
        active_documents += 1
        uid = snapshot.reference.parent.parent.id
        try:
            user = auth.get_user(uid)
        except Exception as exc:
            print(f"::warning::Skipping subscription account {stable_hash((uid,))[:12]}: {type(exc).__name__}")
            continue
        recipient = normalized_email(user.email)
        if not recipient:
            continue
        types = set(settings.get("changeTypes") or []) & ALLOWED_CHANGE_TYPES
        if not types:
            continue
        categories = {str(value).strip() for value in settings.get("categories") or [] if str(value).strip()}
        frequency = str(settings.get("frequency") or "daily")
        if frequency not in {"immediate", "daily", "weekly"}:
            frequency = "daily"
        activation_at = subscription_activation(snapshot, settings)
        group = groups.get(recipient)
        if group is None:
            groups[recipient] = RecipientGroup(
                recipient=recipient,
                activation_at=activation_at,
                change_types=types,
                categories=categories,
                all_categories=not categories,
                frequencies={frequency},
                uids={uid},
            )
        else:
            duplicates += 1
            group.activation_at = min(group.activation_at, activation_at)
            group.change_types.update(types)
            if not categories:
                group.all_categories = True
            group.categories.update(categories)
            group.frequencies.add(frequency)
            group.uids.add(uid)
    return groups, active_documents, duplicates


def frequency_due(frequencies: set[str], now_local: datetime) -> bool:
    if "immediate" in frequencies:
        return True
    if "daily" in frequencies and now_local.hour >= int(os.environ.get("DAILY_SEND_HOUR_LOCAL", "8")):
        return True
    if "weekly" in frequencies:
        weekday = int(os.environ.get("WEEKLY_SEND_WEEKDAY", "0"))
        hour = int(os.environ.get("WEEKLY_SEND_HOUR_LOCAL", "8"))
        if now_local.weekday() == weekday and now_local.hour >= hour:
            return True
    return False


def event_matches(group: RecipientGroup, event: AlertEvent) -> bool:
    if event.change_type not in group.change_types:
        return False
    return group.all_categories or not event.category or event.category in group.categories


def bounded_keys(values: Iterable[str], limit: int = 2000) -> list[str]:
    unique = list(dict.fromkeys(str(value) for value in values if value))
    return unique[-limit:]


def build_email(site_url: str, events: list[AlertEvent]) -> tuple[str, str, str]:
    maximum = int(os.environ.get("MAX_EVENTS_PER_EMAIL", "50"))
    displayed = events[:maximum]
    subject = f"Nanaimo Bylaw Tracker: {len(events)} update{'s' if len(events) != 1 else ''}"
    text_rows = []
    html_rows = []
    for event in displayed:
        local_date = event.occurred_at.astimezone(TZ)
        when = f"{local_date.strftime('%B')} {local_date.day}, {local_date.year}"
        type_label = event.change_type.title()
        text_rows.append(f"- {event.title}\n  {type_label} · {event.source} · {when}\n  {event.url}")
        html_rows.append(
            "<li style=\"margin:0 0 16px\">"
            f"<a href=\"{html.escape(event.url, quote=True)}\" style=\"font-weight:700;color:#0068b5\">"
            f"{html.escape(event.title)}</a><br>"
            f"<span style=\"color:#52657a\">{html.escape(type_label)} · {html.escape(event.source)} · {html.escape(when)}</span>"
            "</li>"
        )
    remainder = len(events) - len(displayed)
    if remainder:
        text_rows.append(f"- Plus {remainder} additional updates. Open the site to review them.")
        html_rows.append(f"<li>Plus {remainder} additional updates. Open the site to review them.</li>")
    manage_url = f"{site_url}/account.html#account-subscriptions"
    text_body = (
        "Nanaimo Bylaw Tracker updates\n\n"
        + "\n\n".join(text_rows)
        + f"\n\nManage or turn off alerts: {manage_url}\n"
        + "Official City of Nanaimo and eSCRIBE records remain the ultimate source.\n"
    )
    html_body = (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;color:#17324d;line-height:1.5\">"
        "<div style=\"max-width:680px;margin:auto\">"
        "<h1 style=\"font-size:24px\">Nanaimo Bylaw Tracker updates</h1>"
        f"<ul style=\"padding-left:22px\">{''.join(html_rows)}</ul>"
        f"<p><a href=\"{html.escape(manage_url, quote=True)}\">Manage or turn off email alerts</a></p>"
        "<p style=\"font-size:12px;color:#63768a\">Official City of Nanaimo and eSCRIBE records remain the ultimate source. "
        "Hesh co. — Nanaimo Bylaw Tracker</p></div></body></html>"
    )
    return subject, text_body, html_body


def send_test(db, site_url: str, recipient: str, events: list[AlertEvent], dry_run: bool) -> dict[str, Any]:
    groups, active_documents, duplicates = load_recipient_groups(db)
    sample = events[: min(3, len(events))]
    if not sample:
        sample = [AlertEvent(
            key="test:sample",
            change_type="new",
            category="Other",
            title="Subscription delivery test",
            url=f"{site_url}/account.html",
            occurred_at=datetime.now(timezone.utc),
            source="System test",
        )]
    subject, text_body, html_body = build_email(site_url, sample)
    subject = "TEST — " + subject
    if not dry_run:
        smtp_send(normalized_email(recipient), subject, text_body, html_body)
    return {
        "mode": "test-dry-run" if dry_run else "test",
        "activeSubscriptionDocuments": active_documents,
        "uniqueActiveRecipients": len(groups),
        "duplicateSubscriptionDocuments": duplicates,
        "testRecipientHash": email_state_id(recipient),
        "testItemCount": len(sample),
        "sent": 0 if dry_run else 1,
    }


def run_delivery(db, site_url: str, events: list[AlertEvent], dry_run: bool) -> dict[str, Any]:
    groups, active_documents, duplicates = load_recipient_groups(db)
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(TZ)
    max_emails = int(os.environ.get("MAX_EMAILS_PER_RUN", "100"))
    pause = float(os.environ.get("SMTP_SEND_DELAY_SECONDS", "0.2"))
    sent = 0
    skipped_not_due = 0
    skipped_no_match = 0
    pending = 0
    ignored = 0
    failed = 0

    for recipient in sorted(groups):
        group = groups[recipient]
        state_ref = db.collection("subscriptionEmailDeliveries").document(email_state_id(recipient))
        state = state_ref.get().to_dict() or {}
        delivered_list = list(state.get("deliveredKeys") or [])
        ignored_list = list(state.get("ignoredKeys") or [])
        delivered_keys = set(delivered_list)
        ignored_keys = set(ignored_list)
        known_keys = delivered_keys | ignored_keys
        eligible = [
            event for event in events
            if event.occurred_at >= group.activation_at and event.key not in known_keys
        ]
        matched = [event for event in eligible if event_matches(group, event)]
        newly_ignored = [event.key for event in eligible if not event_matches(group, event)]
        ignored += len(newly_ignored)

        if not matched:
            skipped_no_match += 1
            if newly_ignored and not dry_run:
                state_ref.set({
                    "ignoredKeys": bounded_keys([*ignored_list, *newly_ignored]),
                    "lastEvaluatedAt": firestore.SERVER_TIMESTAMP,
                    "recipientEmailHash": email_state_id(recipient),
                    "accountCount": len(group.uids),
                }, merge=True)
            continue

        if not frequency_due(group.frequencies, now_local):
            skipped_not_due += 1
            pending += len(matched)
            if newly_ignored and not dry_run:
                state_ref.set({
                    "ignoredKeys": bounded_keys([*ignored_list, *newly_ignored]),
                    "lastEvaluatedAt": firestore.SERVER_TIMESTAMP,
                    "recipientEmailHash": email_state_id(recipient),
                    "accountCount": len(group.uids),
                }, merge=True)
            continue

        if sent >= max_emails:
            pending += len(matched)
            continue

        subject, text_body, html_body = build_email(site_url, matched)
        try:
            if not dry_run:
                smtp_send(recipient, subject, text_body, html_body)
                if pause > 0:
                    time.sleep(pause)
            if not dry_run:
                state_ref.set({
                    "deliveredKeys": bounded_keys([*delivered_list, *(event.key for event in matched)]),
                    "ignoredKeys": bounded_keys([*ignored_list, *newly_ignored]),
                    "lastSentAt": firestore.SERVER_TIMESTAMP,
                    "lastEvaluatedAt": firestore.SERVER_TIMESTAMP,
                    "lastItemCount": len(matched),
                    "frequencies": sorted(group.frequencies),
                    "accountCount": len(group.uids),
                    "recipientEmailHash": email_state_id(recipient),
                }, merge=True)
            sent += 1
        except Exception as exc:
            failed += 1
            print(f"::error::Subscription delivery failed for recipient {email_state_id(recipient)[:12]}: {type(exc).__name__}: {exc}")

    result = {
        "mode": "dry-run" if dry_run else "send",
        "eventCount": len(events),
        "activeSubscriptionDocuments": active_documents,
        "uniqueActiveRecipients": len(groups),
        "duplicateSubscriptionDocuments": duplicates,
        "sent": 0 if dry_run else sent,
        "wouldSend": sent if dry_run else None,
        "failed": failed,
        "pendingItemCount": pending,
        "ignoredItemCount": ignored,
        "skippedNotDue": skipped_not_due,
        "skippedNoMatch": skipped_no_match,
        "maxEmailsPerRun": max_emails,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Evaluate subscriptions without sending or updating delivery state.")
    parser.add_argument("--test-recipient", help="Send one test email to this address without updating subscriber delivery state.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    site_url = require_site_url()
    events = collected_events(site_url)
    db = init_firebase()
    if args.test_recipient:
        recipient = normalized_email(args.test_recipient)
        if not recipient or "@" not in recipient:
            raise RuntimeError("--test-recipient must be a valid email address.")
        result = send_test(db, site_url, recipient, events, args.dry_run)
    else:
        result = run_delivery(db, site_url, events, args.dry_run)
    write_status(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
