"""Merge rule-based entries with LLM-enriched entries. Rules always win."""
from __future__ import annotations

from typing import Any

from .enricher import EnrichmentResult
from .loader import BusinessRules

RULE_CONFIDENCE = 1.0
LLM_CONFIDENCE = 0.6
HUMAN_CONFIDENCE = 0.95


def merge_table(
    rule_entity: dict[str, Any] | None,
    enriched: EnrichmentResult,
) -> dict[str, Any]:
    """Rule fields override LLM fields. Provenance recorded per field."""
    out: dict[str, Any] = {
        "purpose": None,
        "synonyms": [],
        "rules_refs": [],
        "columns": {},
        "provenance": {},
        "confidence": {},
    }

    # purpose
    if rule_entity and rule_entity.get("purpose"):
        out["purpose"] = rule_entity["purpose"]
        out["provenance"]["purpose"] = "rule"
        out["confidence"]["purpose"] = RULE_CONFIDENCE
    elif enriched.purpose:
        out["purpose"] = enriched.purpose
        out["provenance"]["purpose"] = "llm"
        out["confidence"]["purpose"] = LLM_CONFIDENCE

    # synonyms — union, rules first, dedup case-insensitively
    syns: list[str] = []
    seen: set[str] = set()
    if rule_entity:
        for s in rule_entity.get("synonyms", []):
            if s.lower() not in seen:
                syns.append(s)
                seen.add(s.lower())
    for s in enriched.synonyms:
        if s.lower() not in seen:
            syns.append(s)
            seen.add(s.lower())
    out["synonyms"] = syns
    out["provenance"]["synonyms"] = "rule+llm" if rule_entity and rule_entity.get("synonyms") else "llm"
    out["confidence"]["synonyms"] = RULE_CONFIDENCE if rule_entity and rule_entity.get("synonyms") else LLM_CONFIDENCE

    if rule_entity:
        out["rules_refs"] = list(rule_entity.get("rules_refs", []))

    return out


def merge_column(
    rule_column: dict[str, Any] | None,
    enriched: EnrichmentResult,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "purpose": None,
        "synonyms": [],
        "value_map": {},
        "notes": None,
        "provenance": {},
        "confidence": {},
    }

    # purpose
    if rule_column and rule_column.get("purpose"):
        out["purpose"] = rule_column["purpose"]
        out["provenance"]["purpose"] = "rule"
        out["confidence"]["purpose"] = RULE_CONFIDENCE
    elif enriched.purpose:
        out["purpose"] = enriched.purpose
        out["provenance"]["purpose"] = "llm"
        out["confidence"]["purpose"] = LLM_CONFIDENCE

    # synonyms
    syns: list[str] = []
    seen: set[str] = set()
    if rule_column:
        for s in rule_column.get("synonyms", []):
            if s.lower() not in seen:
                syns.append(s)
                seen.add(s.lower())
    for s in enriched.synonyms:
        if s.lower() not in seen:
            syns.append(s)
            seen.add(s.lower())
    out["synonyms"] = syns
    out["provenance"]["synonyms"] = "rule" if rule_column and rule_column.get("synonyms") else "llm"
    out["confidence"]["synonyms"] = RULE_CONFIDENCE if rule_column and rule_column.get("synonyms") else LLM_CONFIDENCE

    # value_map — rule wins wholesale if present, else LLM's
    if rule_column and rule_column.get("value_map"):
        out["value_map"] = rule_column["value_map"]
        out["provenance"]["value_map"] = "rule"
        out["confidence"]["value_map"] = RULE_CONFIDENCE
    elif enriched.value_map:
        out["value_map"] = enriched.value_map
        out["provenance"]["value_map"] = "llm"
        out["confidence"]["value_map"] = LLM_CONFIDENCE

    # notes — rule wins
    if rule_column and rule_column.get("notes"):
        out["notes"] = rule_column["notes"]
        out["provenance"]["notes"] = "rule"
        out["confidence"]["notes"] = RULE_CONFIDENCE
    elif enriched.notes:
        out["notes"] = enriched.notes
        out["provenance"]["notes"] = "llm"
        out["confidence"]["notes"] = LLM_CONFIDENCE

    return out