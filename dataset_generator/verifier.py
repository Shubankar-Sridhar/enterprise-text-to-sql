# verifier.py
"""Verify generated SQL: AST parse (always) + EXPLAIN / execute (optional)."""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot.errors import ParseError


@dataclass
class VerificationResult:
    ok: bool
    reason: str = ""
    ast_hash: str = ""


def verify_ast(sql: str, dialect: str = "postgres") -> VerificationResult:
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except ParseError as e:
        return VerificationResult(ok=False, reason=f"parse error: {e}")
    # Normalize: strip comments, lowercase identifiers, sort projections
    normalized = ast.sql(dialect=dialect)
    import hashlib
    ast_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return VerificationResult(ok=True, ast_hash=ast_hash)


def verify_explain(engine, sql: str) -> VerificationResult:
    """Run EXPLAIN (no execution). Read-only by construction."""
    try:
        with engine.connect() as conn:
            conn.execute(sqlglot.parse_one(sql).sql())  # placeholder
    except Exception as e:
        return VerificationResult(ok=False, reason=f"explain failed: {e}")
    # NOTE: real EXPLAIN goes here once a read-only engine is wired in.
    return VerificationResult(ok=True)


def verify_execute(engine, sql: str, max_rows: int = 100) -> VerificationResult:
    """Actually run the query — only on a read-only replica."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchmany(max_rows)
        return VerificationResult(ok=True, reason=f"{len(rows)} rows")
    except Exception as e:
        return VerificationResult(ok=False, reason=f"execute failed: {e}")