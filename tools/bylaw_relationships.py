#!/usr/bin/env python3
"""Infer amendment, repeal, replacement, and consolidation relationships."""
from __future__ import annotations

from typing import Any
import re

NUMBER = r"\d{3,4}(?:\.\d+)*"
BYLAW_REF = rf"(?:City\s+of\s+Nanaimo\s+)?(?:[A-Z][A-Za-z0-9&,'’()\- ]{{0,140}}\s+)?Bylaw(?:\s+\d{{4}})?(?:\s*,?\s*No\.?)?\s*({NUMBER})"


def normalize_number(value: Any) -> str:
    return str(value or "").strip().rstrip(".")


def _find(pattern: str, text: str) -> list[str]:
    return [normalize_number(value) for value in re.findall(pattern, text, flags=re.I | re.S)]


def infer_relationships(current_number: str, text: str) -> dict[str, list[str]]:
    current = normalize_number(current_number)
    source = " ".join((text or "").replace("\xa0", " ").split())
    result = {
        "amends": [],
        "repeals": [],
        "replaces": [],
        "consolidates": [],
        "amended_by": [],
        "repealed_by": [],
        "replaced_by": [],
        "consolidated_by": [],
    }

    # Decimal amendment numbers conventionally identify their base bylaw.
    if "." in current:
        result["amends"].append(current.split(".", 1)[0])

    verb_patterns = {
        "amends": rf"(?:amend(?:s|ed|ing)?|amendment\s+to)\s+(?:the\s+)?{BYLAW_REF}",
        "repeals": rf"(?:repeal(?:s|ed|ing)?|hereby\s+repeal(?:s|ed)?)\s+(?:and\s+replace(?:s|d|ing)?\s+)?(?:the\s+)?{BYLAW_REF}",
        "replaces": rf"(?:replace(?:s|d|ing)?)\s+(?:the\s+)?{BYLAW_REF}",
        "consolidates": rf"(?:consolidat(?:e|es|ed|ing|ion)\s+(?:of\s+)?)\s*(?:the\s+)?{BYLAW_REF}",
    }
    reverse_patterns = {
        "amends": rf"{BYLAW_REF}\s+(?:is\s+hereby\s+)?amend(?:ed|s)?",
        "repeals": rf"{BYLAW_REF}\s+(?:is\s+hereby\s+)?repeal(?:ed|s)?",
        "replaces": rf"{BYLAW_REF}\s+(?:is\s+hereby\s+)?replace(?:d|s)?",
        "consolidates": rf"{BYLAW_REF}\s+(?:is\s+)?consolidat(?:ed|es)?",
        "replaced_by": rf"{BYLAW_REF}\s+(?:was|is|has\s+been)?\s*replaced\s+by\s+{BYLAW_REF}",
        "repealed_by": rf"{BYLAW_REF}\s+(?:was|is|has\s+been)?\s*repealed\s+by\s+{BYLAW_REF}",
        "amended_by": rf"{BYLAW_REF}\s+(?:was|is|has\s+been)?\s*amended\s+by\s+{BYLAW_REF}",
    }

    for key, pattern in verb_patterns.items():
        result[key].extend(_find(pattern, source))

    for key, pattern in reverse_patterns.items():
        matches = re.findall(pattern, source, flags=re.I | re.S)
        for match in matches:
            values = match if isinstance(match, tuple) else (match,)
            if key.endswith("_by") and len(values) >= 2:
                subject, actor = normalize_number(values[0]), normalize_number(values[-1])
                if subject == current:
                    result[key].append(actor)
                elif actor == current:
                    forward = {
                        "amended_by": "amends",
                        "repealed_by": "repeals",
                        "replaced_by": "replaces",
                    }[key]
                    result[forward].append(subject)
            elif values:
                result[key].append(normalize_number(values[0]))


    # Common enactment wording: “Bylaw No. 4000 and all amendments are hereby repealed.”
    repeal_reference_pattern = rf"{BYLAW_REF}(?:\s+and\s+(?:all\s+)?(?:its\s+)?amendments?)?\s+(?:is|are)\s+(?:hereby\s+)?repealed"
    result["repeals"].extend(_find(repeal_reference_pattern, source))

    replace_reference_pattern = rf"{BYLAW_REF}\s+(?:is|are)\s+(?:hereby\s+)?replaced"
    result["replaces"].extend(_find(replace_reference_pattern, source))

    for key, values in result.items():
        result[key] = sorted({
            value for value in values
            if value and value != current
        })
    return result


def relationship_targets(relationships: dict[str, list[str]]) -> list[str]:
    return sorted({
        value
        for key, values in relationships.items()
        if not key.endswith("_by")
        for value in values
    })


def build_relationship_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_number = {
        normalize_number(record.get("number")): record
        for record in records
        if record.get("number")
    }

    for record in records:
        relationships = record.setdefault("relationships", {})
        for key in (
            "amends", "repeals", "replaces", "consolidates",
            "amended_by", "repealed_by", "replaced_by", "consolidated_by",
        ):
            relationships[key] = sorted(set(relationships.get(key, [])))

    reverse_map = {
        "amends": "amended_by",
        "repeals": "repealed_by",
        "replaces": "replaced_by",
        "consolidates": "consolidated_by",
    }
    for source_number, record in by_number.items():
        for forward, reverse in reverse_map.items():
            for target_number in record["relationships"].get(forward, []):
                target = by_number.get(target_number)
                if target:
                    target["relationships"].setdefault(reverse, [])
                    target["relationships"][reverse].append(source_number)

    edges = []
    for number, record in by_number.items():
        relationships = record["relationships"]
        for key in relationships:
            relationships[key] = sorted(set(relationships[key]))

        if relationships.get("repealed_by"):
            legal_status = "Repealed"
        elif relationships.get("replaced_by"):
            legal_status = "Replaced"
        elif relationships.get("amends"):
            legal_status = "Amendment bylaw"
        elif relationships.get("repeals"):
            legal_status = "Repealing bylaw"
        elif relationships.get("replaces"):
            legal_status = "Replacement bylaw"
        elif "consolidat" in f"{record.get('title', '')} {record.get('description', '')}".lower():
            legal_status = "Consolidated"
        else:
            legal_status = "Published"

        record["legal_status"] = legal_status
        record["relationship_count"] = sum(len(values) for values in relationships.values())
        for relationship_type in ("amends", "repeals", "replaces", "consolidates"):
            for target in relationships.get(relationship_type, []):
                edges.append({
                    "source": number,
                    "target": target,
                    "type": relationship_type,
                    "source_title": record.get("title"),
                    "target_title": by_number.get(target, {}).get("title"),
                    "target_collected": target in by_number,
                })

    collected_repealed_or_replaced = sorted({
        edge["target"]
        for edge in edges
        if edge["type"] in {"repeals", "replaces"} and edge["target_collected"]
    })
    historical_repealed_or_replaced = sorted({
        edge["target"]
        for edge in edges
        if edge["type"] in {"repeals", "replaces"} and not edge["target_collected"]
    })

    return {
        "record_count": len(records),
        "edge_count": len(edges),
        "collected_repealed_or_replaced_count": len(collected_repealed_or_replaced),
        "historical_repealed_or_replaced_count": len(historical_repealed_or_replaced),
        "collected_repealed_or_replaced": collected_repealed_or_replaced,
        "historical_repealed_or_replaced": historical_repealed_or_replaced,
        "edges": edges,
    }
