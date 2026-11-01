"""LLM gap-filler. Provider-agnostic; returns structured JSON per item."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

PROMPT_DIR = Path(__file__).parent / "prompts"

def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Caching — every LLM call is keyed by (model, prompt_hash)
# ---------------------------------------------------------------------------

@dataclass
class EnrichmentResult:
    purpose: str | None
    synonyms: list[str]
    value_map: dict[str, list[str]]
    notes: str | None
    raw: dict[str, Any]


class Enricher:
    def __init__(
        self,
        llm: Callable[[str, str], str],
        model_name: str,
        cache_dir: Path | None = None,
    ):
        """
        llm: function (system_prompt, user_prompt) -> JSON string
        model_name: identifier used in the cache key
        cache_dir: where to store/read cached responses
        """
        self.llm = llm
        self.model_name = model_name
        self.cache_dir = cache_dir or Path(".cache/context_enricher")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enrich_table(
        self,
        table_key: str,
        table_meta: dict[str, Any],
        existing_purpose: str | None,
    ) -> EnrichmentResult:
        user = _load_prompt("table_purpose.txt").format(
            table_key=table_key,
            column_summary=_summarize_columns(table_meta),
            existing_purpose=existing_purpose or "(none)",
        )
        raw = self._call_cached("table_purpose", user)
        return EnrichmentResult(
            purpose=raw.get("purpose"),
            synonyms=raw.get("synonyms", []),
            value_map={},
            notes=raw.get("notes"),
            raw=raw,
        )

    def enrich_column(
        self,
        column_key: str,
        column_meta: dict[str, Any],
        table_purpose: str | None,
        sample_values: list[Any] | None = None,
        existing_purpose: str | None = None,
    ) -> EnrichmentResult:
        user = _load_prompt("column_purpose.txt").format(
            column_key=column_key,
            column_type=column_meta.get("type"),
            nullable=column_meta.get("nullable"),
            table_purpose=table_purpose or "(none)",
            sample_values=json.dumps(sample_values or [], ensure_ascii=False),
            existing_purpose=existing_purpose or "(none)",
        )
        raw = self._call_cached("column_purpose", user)
        return EnrichmentResult(
            purpose=raw.get("purpose"),
            synonyms=raw.get("synonyms", []),
            value_map={},
            notes=raw.get("notes"),
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_cached(self, kind: str, user_prompt: str) -> dict[str, Any]:
        system = (
            "You are a database semantics assistant. "
            "Always reply with a single JSON object. No prose."
        )
        key = hashlib.sha256(
            f"{self.model_name}\n{kind}\n{system}\n{user_prompt}".encode("utf-8")
        ).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        raw_text = self.llm(system, user_prompt)
        parsed = _safe_json(raw_text)
        cache_file.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        return parsed


def _safe_json(text: str) -> dict[str, Any]:
    """Best-effort parse. Strips markdown fences and leading prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _summarize_columns(table_meta: dict[str, Any]) -> str:
    lines = []
    for col in table_meta.get("columns", []):
        flags = []
        if col.get("primary_key"):
            flags.append("PK")
        if not col.get("nullable", True):
            flags.append("NOT NULL")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"  - {col['name']} {col['type']}{suffix}")
    return "\n".join(lines)