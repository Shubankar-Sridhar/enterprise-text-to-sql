"""CLI: generate NL→SQL dataset from schema + context."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from context_builder.main import make_llm_from_env
from .binder import enumerate_all_bindings
from .exporter import write_manifest, write_split
from .realizer import Realizer
from .roundtrip import sqls_equivalent, synthesize_sql
from .splitter import check_leakage, sanity_check_records, split_by_template
from .sql_builder import build_sql
from .verifier import verify_ast, verify_execute


def build_schema_ddl(schema: dict) -> str:
    """Compact DDL for the round-trip prompt. Table + column names only."""
    lines: list[str] = []
    for sch in schema.get("schemas", []):
        for tbl in sch.get("tables", []):
            cols = ", ".join(c["name"] for c in tbl["columns"])
            lines.append(f"{tbl['name']}({cols})")
    return "\n".join(lines)


def record_id(template_id: str, binding, idx: int) -> str:
    parts = [
        template_id,
        binding.table,
        binding.column or "-",
        str(binding.value) if binding.value is not None else "-",
        binding.synonym_used or "-",
        f"{idx:04d}",
    ]
    return ":".join(parts)


def _gold_semantics(binding) -> dict:
    filters = []
    if binding.column and binding.value is not None and not isinstance(binding.value, dict):
        filters.append(f"{binding.column.rsplit('.', 1)[1]} = {binding.value}")
    return {
        "intent": binding.aggregate or "list",
        "grain": None,
        "filters": filters,
    }


def _violates_forbidden_with_question(
    sql: str, question: str, forbidden: list[dict]
) -> str | None:
    """Return the id of a violated rule, or None. Heuristic checks."""
    import re

    for rule in forbidden:
        rid = rule["id"]
        if rid == "never_expose_raw_customer_id":
            m = re.match(r"\s*SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
            if m and "customer_id" in m.group(1).lower():
                return rid
        elif rid == "never_expose_raw_seller_id":
            m = re.match(r"\s*SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
            if m and "seller_id" in m.group(1).lower():
                return rid
        elif rid == "no_cross_schema":
            if re.search(r"\b(auth|storage|vault|realtime|extensions)\.", sql):
                return rid
        elif rid == "revenue_is_gmv":
            if "revenue" in question.lower():
                if re.search(
                    r"SUM\s*\(\s*\w*\.?price", sql, re.IGNORECASE
                ) and "payment_value" not in sql.lower():
                    return rid
    return None


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Generate NL→SQL dataset")
    ap.add_argument("--schema", default="schema.json", type=Path)
    ap.add_argument("--context", default="out/context.json", type=Path)
    ap.add_argument("--out", default="out", type=Path)
    ap.add_argument(
        "--templates",
        nargs="*",
        default=None,
        help="Limit to these template ids (default: all in the tier)",
    )
    ap.add_argument(
        "--tier",
        choices=["easy", "medium", "hard", "all"],
        default="all",
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Use deterministic fallback question generation.",
    )
    ap.add_argument(
        "--no-roundtrip",
        action="store_true",
        help="Skip the round-trip LLM verification (faster, lower quality).",
    )
    ap.add_argument(
        "--verify-execute",
        action="store_true",
        help="Actually execute SQL (needs --db-url).",
    )
    ap.add_argument(
        "--db-url",
        default=None,
        help="Read-only connection URL for --verify-execute.",
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    context = json.loads(args.context.read_text(encoding="utf-8"))
    schema_ddl = build_schema_ddl(schema)

    # ---- LLM setup -------------------------------------------------------
    if args.no_llm:
        llm_call, model_name = None, "fallback"
    else:
        llm_call, model_name = make_llm_from_env()

    realizer = Realizer(llm=llm_call, model_name=model_name, context=context)

    # ---- verification engine (optional) ---------------------------------
    engine = None
    if args.verify_execute:
        if not args.db_url:
            sys.exit("--verify-execute requires --db-url")
        from sqlalchemy import create_engine

        engine = create_engine(args.db_url)

    # ---- generate --------------------------------------------------------
    records: list[dict] = []
    idx = 0
    dropped_ast = 0
    dropped_roundtrip = 0
    dropped_forbidden = 0
    tier_filter = None if args.tier == "all" else args.tier

    for tmpl, binding, brief in enumerate_all_bindings(
        schema,
        context,
        template_ids=args.templates,
        tier=tier_filter,
    ):
        idx += 1
        sql = build_sql(tmpl, binding)

        # 1. AST check
        ast_res = verify_ast(sql)
        if not ast_res.ok:
            dropped_ast += 1
            continue

        # 2. Realize the question
        rq = realizer.realize(tmpl, binding, brief)
        if rq is None:
            continue

        # 3. Round-trip verification
        roundtrip_ok = None
        synth = None
        if not args.no_roundtrip and llm_call is not None:
            synth = synthesize_sql(llm_call, rq.question, schema_ddl)
            roundtrip_ok = synth is not None and sqls_equivalent(sql, synth)
            if not roundtrip_ok:
                dropped_roundtrip += 1
                continue

        # 4. Forbidden-rule check on the synthesized SQL, if we have one
        if synth is not None:
            violated = _violates_forbidden_with_question(
                synth, rq.question, context.get("forbidden", [])
            )
            if violated:
                dropped_forbidden += 1
                continue

        # 5. Optional execute
        exec_rows = None
        if engine is not None:
            res = verify_execute(engine, sql)
            if not res.ok:
                continue
            exec_rows = res.reason

        records.append(
            {
                "id": record_id(tmpl.id, binding, idx),
                "question": rq.question,
                "sql": sql,
                "template_id": tmpl.id,
                "difficulty": tmpl.difficulty,
                "tags": tmpl.tags,
                "split_group_key": tmpl.split_group_key(binding),
                "slots": {
                    "table": binding.table,
                    "column": binding.column,
                    "value": binding.value,
                    "synonym_used": binding.synonym_used,
                },
                "entities_used": [binding.table] if binding.table else [],
                "rules_used": brief.get("rules_refs", []),
                "synonyms_used": (
                    [binding.synonym_used] if binding.synonym_used else []
                ),
                "gold_semantics": _gold_semantics(binding),
                "provenance": {
                    "realizer_model": rq.model_name,
                    "prompt_hash": rq.prompt_hash,
                    "template_version": "1.0",
                    "seed": args.seed,
                },
                "verification": {
                    "ast_ok": True,
                    "ast_hash": ast_res.ast_hash,
                    "roundtrip_ok": roundtrip_ok,
                    "executed_rows": exec_rows,
                },
            }
        )

    # ---- sanity + split + export ----------------------------------------
    sanity = sanity_check_records(records)
    if sanity:
        print("⚠ input sanity issues:", file=sys.stderr)
        for issue in sanity:
            print(f"  {issue}", file=sys.stderr)

    split = split_by_template(records, seed=args.seed)

    leaks = check_leakage(split)
    if leaks:
        print("⚠ leakage detected:", file=sys.stderr)
        for l in leaks[:10]:
            print(f"  {l}", file=sys.stderr)

    write_split(args.out, split)
    write_manifest(
        args.out,
        records,
        split,
        model_name,
        args.seed,
        tier=args.tier,
    )

    print(
        f"✓ {len(records)} records kept "
        f"(dropped: ast={dropped_ast}, roundtrip={dropped_roundtrip}, "
        f"forbidden={dropped_forbidden}) "
        f"→ train={len(split.train)} dev={len(split.dev)} test={len(split.test)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()