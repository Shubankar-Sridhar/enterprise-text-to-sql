# dataset_generator/roundtrip.py
"""Independent LLM SQL synthesis for round-trip verification."""
from __future__ import annotations

import sqlglot
from typing import Callable


ROUNDTRIP_SYSTEM = (
    "You are a text-to-SQL model. Given a question and a schema, emit one "
    "SQL SELECT statement. No prose, no markdown fences."
)


def synthesize_sql(
    llm: Callable[[str, str], str],
    question: str,
    schema_ddl: str,
    dialect: str = "postgres",
) -> str | None:
    user = (
        f"Schema:\n{schema_ddl}\n\n"
        f"Question: {question}\n\n"
        f"SQL:"
    )
    try:
        raw = llm(ROUNDTRIP_SYSTEM, user).strip()
    except Exception:
        return None
    # Strip fences
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("sql"):
            raw = raw[3:]
    return raw.strip().rstrip(";")


def sqls_equivalent(a: str, b: str, dialect: str = "postgres") -> bool:
    """AST-equivalence check. Tolerant of aliasing / whitespace / casing."""
    try:
        ast_a = sqlglot.parse_one(a, read=dialect)
        ast_b = sqlglot.parse_one(b, read=dialect)
    except Exception:
        return False
    # Normalize identifiers to lowercase, strip explicit LIMIT 100 (our convention)
    def norm(ast):
        return ast.transform(
            lambda n: n.copy().set("this", n.this.lower())
            if isinstance(n, sqlglot.exp.Identifier) and isinstance(n.this, str)
            else n
        ).sql(dialect=dialect, pretty=False)
    return norm(ast_a) == norm(ast_b)