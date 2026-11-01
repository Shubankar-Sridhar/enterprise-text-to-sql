"""Resolve ambiguities from context.json into concrete column choices."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AmbiguityBinding:
    term: str
    candidates: list[str]
    chosen: str
    disambiguation_rule: str
    rationale: str


def enumerate_ambiguity_bindings(context: dict) -> list[AmbiguityBinding]:
    out: list[AmbiguityBinding] = []
    for term, spec in (context.get("ambiguities") or {}).items():
        candidates = spec.get("candidates", [])
        if not candidates:
            continue
        rule = spec.get("disambiguation", "")
        chosen = _parse_default(rule, candidates)
        out.append(AmbiguityBinding(
            term=term,
            candidates=candidates,
            chosen=chosen,
            disambiguation_rule=rule,
            rationale=f"'{term}' defaults to {chosen} per rule: {rule}",
        ))
    return out


def _parse_default(rule: str, candidates: list[str]) -> str:
    lower = rule.lower()
    for cand in candidates:
        col = cand.rsplit(".", 1)[1]
        if col in lower:
            return cand
    return sorted(candidates)[0]