"""CLI: build context.json + context.review.json + terminology_map.tsv."""
from __future__ import annotations

import argparse
import json
import os
from socket import timeout
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .enricher import Enricher, EnrichmentResult
from .exporters import write_context, write_review, write_terminology_tsv
from .loader import load_rules, load_schema
from .merger import merge_column, merge_table
from .validator import validate


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# LLM adapter — provider-agnostic. Only used when --no-llm is not passed.
# ---------------------------------------------------------------------------

def make_llm_from_env():
    provider = os.getenv("LLM_PROVIDER", "none").lower()

    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")

        def call(system: str, user: str) -> str:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return r.choices[0].message.content or ""

        return call, model

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        model = os.getenv("LLM_MODEL", "claude-3-5-haiku-latest")

        def call(system: str, user: str) -> str:
            r = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return r.content[0].text

        return call, model

    if provider == "ollama":
        import requests
        model = os.getenv("LLM_MODEL", "llama3.1:8b")
        url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

        def call(system: str, user: str) -> str:
            r = requests.post(url, json={
                "model": model,
                "think": False,
                "stream": False,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }, timeout=(10, 600))
            r.raise_for_status()
            return r.json()["message"]["content"]

        return call, model

    raise SystemExit(
        "No LLM provider configured. Set LLM_PROVIDER=openai|anthropic|ollama."
    )


# ---------------------------------------------------------------------------
# No-LLM enrichment stub
# ---------------------------------------------------------------------------

class _NullEnricher:
    """Used with --no-llm: returns empty enrichment for every item."""

    def enrich_table(self, *_a, **_k) -> EnrichmentResult:
        return EnrichmentResult(purpose=None, synonyms=[], value_map={}, notes=None, raw={})

    def enrich_column(self, *_a, **_k) -> EnrichmentResult:
        return EnrichmentResult(purpose=None, synonyms=[], value_map={}, notes=None, raw={})


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

def build_context(
    schema_path: Path,
    rules_path: Path,
    out_dir: Path,
    llm_call,
    model_name: str,
    cache_dir: Path | None,
    skip_llm: bool,
):
    schema_doc, schema_index = load_schema(schema_path)
    rules = load_rules(rules_path)

    # ---- validation gate -------------------------------------------------
    issues = validate(rules, schema_index)
    if issues:
        print("✗ business_rules.yaml failed validation:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        sys.exit(1)

    print(
        f"✓ rules validated against schema ({len(schema_index.tables)} tables)",
        file=sys.stderr,
    )

    # ---- enrichment setup ------------------------------------------------
    if skip_llm:
        enricher = _NullEnricher()
    else:
        enricher = Enricher(llm=llm_call, model_name=model_name, cache_dir=cache_dir)

    # ---- walk every table in schema.json ---------------------------------
    context: dict = {
        "version": "1.0",
        "generated_at": _utc_iso(),
        "domain": rules.domain,
        "generator_model": model_name,
        "tables": {},
        "metrics": {k: v.model_dump() for k, v in rules.metrics.items()},
        "filters": {k: v.model_dump() for k, v in rules.filters.items()},
        "forbidden": [f.model_dump() for f in rules.forbidden],
        "ambiguities": {k: v.model_dump() for k, v in rules.ambiguities.items()},
    }

    for tkey, tmeta in schema_index.tables.items():
        rule_entity = rules.entities.get(tkey)
        rule_dict = rule_entity.model_dump() if rule_entity else None

        print(f"  • {tkey}", file=sys.stderr)
        table_enriched = enricher.enrich_table(
            tkey,
            tmeta,
            rule_dict.get("purpose") if rule_dict else None,
        )
        merged_table = merge_table(rule_dict, table_enriched)

        for col in tmeta.get("columns", []):
            ckey = f"{tkey}.{col['name']}"
            rule_col = None
            if rule_entity and ckey in rule_entity.columns:
                rule_col = rule_entity.columns[ckey].model_dump()

            samples = _samples_for(schema_doc, tkey, col["name"])

            col_enriched = enricher.enrich_column(
                ckey,
                col,
                table_purpose=merged_table["purpose"],
                sample_values=samples,
                existing_purpose=rule_col.get("purpose") if rule_col else None,
            )
            merged_col = merge_column(rule_col, col_enriched)
            merged_table["columns"][ckey] = merged_col

        context["tables"][tkey] = merged_table

    # ---- write outputs ---------------------------------------------------
    write_context(out_dir, context)
    write_review(out_dir, context, threshold=0.8)
    write_terminology_tsv(out_dir, context)
    print(
        f"✓ wrote context.json, context.review.json, terminology_map.tsv → {out_dir}",
        file=sys.stderr,
    )


def _samples_for(schema_doc: dict, tkey: str, colname: str) -> list:
    """Pull sample_values out of the profiles block, if the extractor produced it."""
    schema_name, table_name = tkey.split(".", 1)
    try:
        return (
            schema_doc["profiles"][schema_name]["tables"][table_name]
            ["columns"][colname]["sample_values"]
        )
    except (KeyError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Build context.json from schema + rules")
    ap.add_argument("--schema", default="schema.json", type=Path)
    ap.add_argument("--rules", default="business_rules.yaml", type=Path)
    ap.add_argument("--out", default="out", type=Path)
    ap.add_argument("--cache-dir", default=".cache/context_enricher", type=Path)
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM enrichment; only apply rules verbatim.",
    )
    args = ap.parse_args()

    if args.no_llm:
        llm_call, model_name = None, "none"
    else:
        llm_call, model_name = make_llm_from_env()

    build_context(
        schema_path=args.schema,
        rules_path=args.rules,
        out_dir=args.out,
        llm_call=llm_call,
        model_name=model_name,
        cache_dir=args.cache_dir,
        skip_llm=args.no_llm,
    )


if __name__ == "__main__":
    main()