"""Enumerate all bindings for all templates across all tables."""
from __future__ import annotations

from typing import Iterator

from .templates import Template, build_registry


def enumerate_all_bindings(
    schema: dict,
    context: dict,
    template_ids: list[str] | None = None,
    tier: str | None = None,
) -> Iterator[tuple[Template, "SlotBinding", dict]]:
    registry = build_registry(schema, context)

    if template_ids:
        templates = [registry[t] for t in template_ids if t in registry]
    else:
        templates = list(registry.values())

    if tier is not None:
        templates = [t for t in templates if t.difficulty == tier]

    for sch in schema.get("schemas", []):
        sname = sch["name"]
        for tbl in sch.get("tables", []):
            tkey = f"{sname}.{tbl['name']}"
            ctx_table = context["tables"].get(tkey)
            if not ctx_table:
                continue

            for tmpl in templates:
                for binding in tmpl.enumerate_bindings(tkey, tbl, context):
                    brief = _enrich_brief(tmpl, binding, tbl, ctx_table)
                    brief.setdefault("difficulty", tmpl.difficulty)
                    yield tmpl, binding, brief


def _enrich_brief(tmpl, binding, table_meta, ctx_table) -> dict:
    brief = tmpl.realize_brief(binding)

    # Defensive: ensure the fallback realizer can always see these fields,
    # even if a template forgot to include them in its realize_brief().
    brief.setdefault("aggregate", binding.aggregate)
    brief.setdefault("column_synonym", binding.synonym_used)

    # Table synonyms
    brief["entity_synonyms"] = ctx_table.get("synonyms", [])
    brief["entity_purpose"] = ctx_table.get("purpose", "")

    # Column synonyms
    if binding.column:
        col_ctx = ctx_table["columns"].get(binding.column, {})
        brief["column_synonyms"] = col_ctx.get("synonyms", [])
        brief["column_purpose"] = col_ctx.get("purpose", "")

    brief["rules_refs"] = ctx_table.get("rules_refs", [])

    # Forward structured-value extras
    if isinstance(binding.value, dict):
        brief.setdefault("top_n", binding.value.get("top_n"))
        brief.setdefault("threshold", binding.value.get("threshold"))
        brief.setdefault("ambiguous_term", binding.value.get("term"))
        brief.setdefault("disambiguation_rule", binding.value.get("rule"))
        if "raw_value" in binding.value:
            brief.setdefault("raw_value", binding.value["raw_value"])
        if "alias_a" in binding.value:
            brief.setdefault("filter_value_synonym", binding.value.get("alias_a"))

    return brief