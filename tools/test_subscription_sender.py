#!/usr/bin/env python3
"""Dependency-light checks for the subscription event and email logic."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import send_subscription_updates as sender


class SubscriptionSenderTests(unittest.TestCase):
    def test_bylaw_events_skip_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "change-log.json"
            path.write_text(json.dumps({"events": [
                {
                    "id": "baseline:7295",
                    "baseline": True,
                    "date": "2026-01-01",
                    "status": "New",
                    "number": "7295",
                    "title": "Old baseline",
                },
                {
                    "id": "2026-07-28T18:17:00-07:00:changed:7295",
                    "date": "2026-07-28T18:17:00-07:00",
                    "status": "Amended",
                    "number": "7295",
                    "title": "Updated bylaw",
                    "category": "Finance",
                },
            ]}), encoding="utf-8")
            with patch.object(sender, "CHANGE_LOG", path):
                events = sender.bylaw_events("https://example.test")
        self.assertEqual(1, len(events))
        self.assertEqual("amended", events[0].change_type)
        self.assertIn("7295", events[0].url)

    def test_council_events_exclude_committee_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "council-change-log.json"
            path.write_text(json.dumps({"events": [
                {
                    "id": "run:council-1",
                    "item_id": "council-1",
                    "date": "2026-07-28T18:17:00-07:00",
                    "meeting_group": "council",
                    "title": "Council adopted Bylaw 7336",
                    "action": "Adopted",
                },
                {
                    "id": "run:committee-1",
                    "item_id": "committee-1",
                    "date": "2026-07-28T18:17:00-07:00",
                    "meeting_group": "committee",
                    "title": "Committee recommendation",
                    "action": "Recommended",
                },
            ]}), encoding="utf-8")
            with patch.object(sender, "COUNCIL_CHANGE_LOG", path):
                events = sender.council_events("https://example.test")
        self.assertEqual(["council:run:council-1"], [event.key for event in events])

    def test_council_change_events_for_same_item_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "council-change-log.json"
            path.write_text(json.dumps({"events": [
                {"id": "run-one:added:item-1", "item_id": "item-1", "date": "2026-07-28T08:00:00-07:00", "meeting_group": "council", "title": "First", "action": "Discussed"},
                {"id": "run-two:changed:item-1", "item_id": "item-1", "date": "2026-07-28T18:00:00-07:00", "meeting_group": "council", "title": "Changed", "action": "Amended"}
            ]}), encoding="utf-8")
            with patch.object(sender, "COUNCIL_CHANGE_LOG", path):
                events = sender.council_events("https://example.test")
        self.assertEqual(2, len({event.key for event in events}))

    def test_event_match_respects_category_and_type(self):
        group = sender.RecipientGroup(
            recipient="person@example.com",
            activation_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            change_types={"amended"},
            categories={"Finance"},
            all_categories=False,
            frequencies={"daily"},
            uids={"uid"},
        )
        matching = sender.AlertEvent(
            key="one",
            change_type="amended",
            category="Finance",
            title="Matching",
            url="https://example.test/one",
            occurred_at=datetime.now(timezone.utc),
            source="Bylaw archive",
        )
        wrong_category = sender.AlertEvent(**{**matching.__dict__, "key": "two", "category": "Animals"})
        self.assertTrue(sender.event_matches(group, matching))
        self.assertFalse(sender.event_matches(group, wrong_category))

    def test_subscription_activation_prefers_activated_timestamp(self):
        snapshot = SimpleNamespace(create_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
        activated = datetime(2026, 7, 1, tzinfo=timezone.utc)
        result = sender.subscription_activation(snapshot, {"activatedAt": activated})
        self.assertEqual(activated, result)


    def test_dry_run_ignores_events_before_activation(self):
        activation = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)

        class FakeSubscriptionSnapshot:
            id = "email"
            create_time = activation
            reference = SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id="uid-1")))
            def to_dict(self):
                return {
                    "active": True,
                    "frequency": "immediate",
                    "changeTypes": ["new"],
                    "categories": [],
                    "activatedAt": activation,
                }

        class FakeStateDocument:
            def get(self):
                return SimpleNamespace(to_dict=lambda: {})
            def set(self, *args, **kwargs):
                raise AssertionError("dry-run must not update delivery state")

        class FakeCollection:
            def stream(self):
                return [FakeSubscriptionSnapshot()]
            def document(self, _):
                return FakeStateDocument()

        class FakeDb:
            def collection_group(self, _):
                return FakeCollection()
            def collection(self, _):
                return FakeCollection()

        before = sender.AlertEvent(
            key="before", change_type="new", category="Other", title="Before",
            url="https://example.test/before",
            occurred_at=datetime(2026, 7, 28, 17, 59, tzinfo=timezone.utc), source="Test"
        )
        after = sender.AlertEvent(
            key="after", change_type="new", category="Other", title="After",
            url="https://example.test/after",
            occurred_at=datetime(2026, 7, 28, 18, 1, tzinfo=timezone.utc), source="Test"
        )
        fake_auth = SimpleNamespace(get_user=lambda uid: SimpleNamespace(email="person@example.com"))
        with patch.object(sender, "auth", fake_auth):
            result = sender.run_delivery(FakeDb(), "https://example.test", [before, after], True)
        self.assertEqual(1, result["wouldSend"])
        self.assertEqual(0, result["sent"])

    def test_email_escapes_collected_titles(self):
        event = sender.AlertEvent(
            key="event",
            change_type="new",
            category="Other",
            title='<script>alert("x")</script>',
            url="https://example.test/?a=1&b=2",
            occurred_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            source="Council activity",
        )
        _, _, html_body = sender.build_email("https://example.test", [event])
        self.assertNotIn("<script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)
        self.assertIn("&amp;", html_body)


if __name__ == "__main__":
    unittest.main()
