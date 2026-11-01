"""Realize a slot binding into a natural-language question via LLM."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .templates import SlotBinding, Template


PROMPT_PATH = Path(__file__).parent / "prompts" / "realize_question.txt"


@dataclass
class RealizedQuestion:
    question: str
    raw: dict
    prompt_hash: str
    model_name: str


class Realizer:
    def __init__(
        self,
        llm: Callable[[str, str], str] | None,
        model_name: str,
        context: dict | None = None,
        cache_dir: Path | None = None,
    ):
        """
        llm:        callable (system_prompt, user_prompt) -> response text.
                    Pass None to force the deterministic fallback.
        model_name: identifier used in the cache key and record metadata.
        context:    the full context.json dict. Required for forbidden-rule
                    injection into the prompt. May be None for easy-tier-only
                    runs — forbidden rules simply won't be injected.
        cache_dir:  where to persist prompt-hash cache.
        """
        self.llm = llm
        self.model_name = model_name
        self.context = context or {}
        self.cache_dir = cache_dir or Path(".cache/dataset_realizer")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.system_prompt = (
            "You are a business analyst writing natural-language questions "
            "for a text-to-SQL benchmark. Reply with a single JSON object."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def realize(
        self,
        template: Template,
        binding: SlotBinding,
        brief: dict,
    ) -> RealizedQuestion | None:
        user_prompt = self._build_prompt(brief)

        if self.llm is None:
            return self._deterministic_fallback(brief)

        raw = self._call_cached(user_prompt)
        q = (raw or {}).get("question", "").strip()
        if not q or len(q) < 5:
            return None
        return RealizedQuestion(
            question=q,
            raw=raw,
            prompt_hash=hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:16],
            model_name=self.model_name,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self, brief: dict) -> str:
        forbidden_lines = self._forbidden_block(brief)
        return PROMPT_PATH.read_text(encoding="utf-8").format(
            intent=brief.get("intent", ""),
            entity_synonyms=", ".join(brief.get("entity_synonyms", [])) or "(none)",
            entity_purpose=brief.get("entity_purpose", ""),
            column_synonyms=", ".join(brief.get("column_synonyms", [])) or "(none)",
            column_purpose=brief.get("column_purpose", ""),
            filter_value=brief.get("raw_value") or "(none)",
            filter_value_synonym=brief.get("filter_value_synonym") or "(none)",
            aggregate=brief.get("aggregate") or "(none)",
            top_n=brief.get("top_n") or "(none)",
            threshold=brief.get("threshold") or "(none)",
            ambiguous_term=brief.get("ambiguous_term") or "(none)",
            disambiguation_rule=brief.get("disambiguation_rule") or "(none)",
            difficulty=brief.get("difficulty", "easy"),
            forbidden_rules=forbidden_lines or "(none)",
        )

    def _forbidden_block(self, brief: dict) -> str:
        """
        Render the forbidden rules that apply to this brief.
        Always includes global rules (those with empty `applies_to`), plus
        any scoped rules whose `id` appears in the brief's rules_refs.
        """
        scoped_ids = set(brief.get("rules_refs") or [])
        lines: list[str] = []
        for rule in self.context.get("forbidden", []) or []:
            if not rule.get("applies_to") or rule["id"] in scoped_ids:
                lines.append(f"- {rule['rule']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _call_cached(self, user_prompt: str) -> dict:
        key = hashlib.sha256(
            f"{self.model_name}\n{self.system_prompt}\n{user_prompt}".encode("utf-8")
        ).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        raw_text = self.llm(self.system_prompt, user_prompt)
        parsed = _safe_json(raw_text)
        cache_file.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        return parsed

    # ------------------------------------------------------------------
    # Deterministic fallback (used with --no-llm)
    # ------------------------------------------------------------------

    def _deterministic_fallback(self, brief: dict) -> RealizedQuestion:
        intent = brief.get("intent", "list rows")
        entity = (brief.get("entity_synonyms") or ["records"])[0]
        value = brief.get("filter_value_synonym") or brief.get("raw_value") or ""
        agg = brief.get("aggregate")
        top_n = brief.get("top_n")
        threshold = brief.get("threshold")
        ambiguous = brief.get("ambiguous_term")

        if agg == "count":
            q = f"How many {entity} are marked '{value}'?"
        elif agg == "count_distinct":
            col = brief.get("column_synonym") or "values"
            q = f"How many distinct {col} are there in {entity}?"
        elif agg in ("avg", "sum", "min", "max"):
            col = (brief.get("column_synonyms") or ["amount"])[0]
            q = f"What is the {agg} {col} of {entity}?"
        elif top_n:
            col = (brief.get("column_synonyms") or ["category"])[0]
            q = f"What are the top {top_n} {col} in {entity}?"
        elif threshold:
            q = f"Which {entity} have more than {threshold} records?"
        elif ambiguous:
            q = f"List the distinct {ambiguous}."
        elif value:
            q = f"List {entity} with status '{value}'."
        else:
            q = f"Show {entity}."

        return RealizedQuestion(
            question=q,
            raw={"question": q, "fallback": True},
            prompt_hash="fallback",
            model_name="fallback",
        )


def _safe_json(text: str) -> dict:
    """Best-effort parse. Strips markdown fences and leading prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(text[s : e + 1])
    except json.JSONDecodeError:
        return {}