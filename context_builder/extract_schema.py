#!/usr/bin/env python3
"""
extract_schema.py — universal, multi-schema schema + profile extractor.

Reads any SQLAlchemy-supported database (Supabase/Postgres, MySQL, SQLite,
SQL Server, Oracle, Snowflake, BigQuery, Redshift, …) and writes a single
schema.json containing every table of every non-system schema, with:

  • column definitions (type, nullable, default, PK, autoincrement, comment)
  • primary keys, foreign keys, indexes
  • relationships map keyed by "<schema>.<table>"
  • per-schema profiling: row counts, distinct counts, null ratios,
    sample values, semantic type, and estimated table size

Usage:
  python extract_schema.py --url "$DATABASE_URL" --out schema.json
  python extract_schema.py --url "$DATABASE_URL" --schemas public analytics
  python extract_schema.py --url "$DATABASE_URL" --sample-rows 5000

Env:
  DATABASE_URL — used if --url is omitted.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, inspect, text


SYSTEM_SCHEMAS = {
    "information_schema", "pg_catalog", "pg_toast",
    "mysql", "performance_schema", "sys",
    "sysadmin",                 # SQL Server
    "guest", "db_owner", "db_accessadmin", "db_securityadmin",
    "db_ddladmin", "db_backupoperator", "db_datareader",
    "db_datawriter", "db_denydatareader", "db_denydatawriter",
    "INFORMATION_SCHEMA",
    "auth",
    "extensions",
    "realtime",
    "storage",
    "vault",
    "graphql",
    "graphql_public",
    "pgbouncer",
    "supabase_migrations",
    "supabase_functions",
    "net",
    "cron"
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mask_url(url: str) -> str:
    """Replace password with *** so we can print/store it safely."""
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


def human_bytes(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "kB", "MB", "GB", "TB", "PB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f}".rstrip("0").rstrip(".") + f" {unit}"
        n /= 1024
    return f"{n:.1f} EB"


def type_to_string(col_type) -> str:
    try:
        return str(col_type).upper()
    except Exception:
        return "UNKNOWN"


def semantic_type(series: pd.Series, col_name: str) -> str:
    name = col_name.lower()
    if series.empty:
        return "unknown"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "temporal"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    nunique = series.nunique(dropna=True)
    total = len(series)
    if total and nunique == total and any(k in name for k in ("id", "uuid", "key")):
        return "identifier"
    if total and nunique / total < 0.5:
        return "categorical"
    if any(k in name for k in ("name", "description", "comment", "message", "title")):
        return "text"
    return "categorical" if nunique < total else "identifier"


def safe_sample(values, n=5):
    out = []
    for v in values:
        if len(out) >= n:
            break
        try:
            if pd.isna(v):
                continue
        except Exception:
            pass
        if isinstance(v, (pd.Timestamp, datetime)):
            v = v.isoformat()
        if hasattr(v, "item"):
            try:
                v = v.item()
            except Exception:
                pass
        if isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        try:
            json.dumps(v)
            out.append(v)
        except (TypeError, ValueError):
            out.append(str(v))
    return out



def list_user_schemas(inspector, include=None):
    """Return schemas to extract, preserving DB order, excluding system ones."""
    try:
        all_schemas = inspector.get_schema_names()
    except Exception:
        all_schemas = ["public"]
    out = []
    for s in all_schemas:
        if s in SYSTEM_SCHEMAS:
            continue
        if s.lower() in SYSTEM_SCHEMAS:
            continue
        if s.startswith("pg_"):
            continue
        out.append(s)
    if include:
        wanted = {x.lower() for x in include}
        out = [s for s in out if s.lower() in wanted]
    return out


def columns_for(inspector, schema, table):
    cols = inspector.get_columns(table, schema=schema)
    try:
        pk = inspector.get_pk_constraint(table, schema=schema).get(
            "constrained_columns"
        ) or []
    except Exception:
        pk = []
    out = []
    for c in cols:
        out.append({
            "name": c["name"],
            "type": type_to_string(c["type"]),
            "nullable": bool(c.get("nullable", True)),
            "default": str(c["default"]) if c.get("default") is not None else None,
            "primary_key": c["name"] in pk,
            "autoincrement": bool(c.get("autoincrement", False)),
            "comment": c.get("comment"),
        })
    return out


def fks_for(inspector, schema, table):
    try:
        fks = inspector.get_foreign_keys(table, schema=schema)
    except Exception:
        return []
    out = []
    for fk in fks:
        out.append({
            "constrained_columns": fk.get("constrained_columns", []),
            "referred_schema": fk.get("referred_schema") or schema,
            "referred_table": fk.get("referred_table"),
            "referred_columns": fk.get("referred_columns", []),
            "name": fk.get("name"),
        })
    return out


def indexes_for(inspector, schema, table):
    try:
        idxs = inspector.get_indexes(table, schema=schema)
    except Exception:
        return []
    return [{
        "name": i.get("name"),
        "column_names": i.get("column_names", []),
        "unique": bool(i.get("unique", False)),
    } for i in idxs]


def table_comment(inspector, schema, table):
    try:
        return inspector.get_table_comment(table, schema=schema).get("text") or ""
    except Exception:
        return ""



def estimate_size_bytes(engine, schema, table, fallback_df=None):
    try:
        with engine.connect() as conn:
            dialect = engine.dialect.name
            if dialect == "postgresql":
                return int(conn.execute(
                    text("SELECT pg_total_relation_size(:t)"),
                    {"t": f"{schema}.{table}"},
                ).scalar() or 0)
            if dialect in ("mysql", "mariadb"):
                return int(conn.execute(
                    text(
                        "SELECT data_length + index_length FROM information_schema.tables "
                        "WHERE table_schema=:s AND table_name=:t"
                    ),
                    {"s": schema, "t": table},
                ).scalar() or 0)
    except Exception:
        pass
    if fallback_df is not None and not fallback_df.empty:
        return int(fallback_df.memory_usage(deep=True).sum())
    return 0


def profile_table(engine, schema, table, sample_rows):
    qualified = f'"{schema}"."{table}"'
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar() or 0

    if total == 0:
        return {
            "row_count": 0,
            "column_count": 0,
            "columns": {},
            "estimated_size": {"total_bytes": 0, "total_pretty": "0 B"},
        }

    limit = min(int(sample_rows), int(total))
    try:
        df = pd.read_sql(
            text(f"SELECT * FROM {qualified} LIMIT :n"),
            engine,
            params={"n": limit},
        )
    except Exception as e:
        print(f"    ! sample read failed on {schema}.{table}: {e}", file=sys.stderr)
        df = pd.DataFrame()

    columns_profile = {}
    for col in df.columns:
        s = df[col]
        total_count = int(len(s))
        null_count = int(s.isna().sum())
        distinct_count = int(s.nunique(dropna=True))

        # For large tables recompute distinct exactly on the DB
        if total > limit:
            try:
                with engine.connect() as conn:
                    distinct_count = int(conn.execute(
                        text(f'SELECT COUNT(DISTINCT "{col}") FROM {qualified}')
                    ).scalar() or distinct_count)
            except Exception:
                pass

        null_ratio = round(null_count / total_count, 3) if total_count else 0.0
        unique_ratio = round(distinct_count / total, 3) if total else 0.0

        columns_profile[col] = {
            "total_count": int(total),
            "distinct_count": distinct_count,
            "null_count": null_count,
            "null_ratio": null_ratio,
            "unique_ratio": unique_ratio,
            "semantic_type": semantic_type(s, col),
            "sample_values": safe_sample(s.dropna().unique().tolist(), 5),
        }

    size_bytes = estimate_size_bytes(engine, schema, table, fallback_df=df)
    return {
        "row_count": int(total),
        "column_count": int(len(df.columns)),
        "columns": columns_profile,
        "estimated_size": {
            "total_bytes": int(size_bytes),
            "total_pretty": human_bytes(size_bytes),
        },
    }



def build_schema(url: str, sample_rows: int = 1000, include_schemas=None):
    engine = create_engine(url, future=True)
    inspector = inspect(engine)
    dialect = engine.dialect.name

    schemas_to_use = list_user_schemas(inspector, include=include_schemas)
    if not schemas_to_use:
        # Fallback: some DBs (SQLite) have no real schema concept
        schemas_to_use = [None] if dialect == "sqlite" else ["public"]

    schema_entries = []
    profiles = {}
    relationships = {}

    for schema in schemas_to_use:
        try:
            tables = inspector.get_table_names(schema=schema)
        except Exception:
            tables = []
        # Also capture views so the schema is complete
        try:
            views = inspector.get_view_names(schema=schema)
        except Exception:
            views = []
        all_objects = list(tables) + [v for v in views if v not in tables]

        if not all_objects:
            continue

        schema_key = schema or "main"
        schema_entry = {"name": schema_key, "tables": []}
        profiles[schema_key] = {"table_count": len(all_objects), "tables": {}}

        for table in all_objects:
            print(f"  • {schema_key}.{table}", file=sys.stderr)

            cols = columns_for(inspector, schema, table)
            pks = [c["name"] for c in cols if c["primary_key"]]
            fks = fks_for(inspector, schema, table)
            idxs = indexes_for(inspector, schema, table)
            comment = table_comment(inspector, schema, table)

            schema_entry["tables"].append({
                "name": table,
                "description": comment,
                "schema": schema_key,
                "columns": cols,
                "primary_keys": pks,
                "foreign_keys": fks,
                "indexes": idxs,
            })

            if fks:
                relationships[f"{schema_key}.{table}"] = fks

            try:
                profiles[schema_key]["tables"][table] = profile_table(
                    engine, schema, table, sample_rows
                )
            except Exception as e:
                print(f"    ! profiling failed: {e}", file=sys.stderr)
                profiles[schema_key]["tables"][table] = {
                    "row_count": 0,
                    "column_count": len(cols),
                    "columns": {},
                    "estimated_size": {"total_bytes": 0, "total_pretty": "0 B"},
                }

        schema_entries.append(schema_entry)

    return {
        "version": "1.0",
        "extracted_at": utc_now_iso(),
        "database": {"url": mask_url(url), "type": dialect},
        "schemas": schema_entries,
        "relationships": relationships,
        "profiles": profiles,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Extract DB schema → schema.json")
    ap.add_argument("--url", default=os.getenv("DATABASE_URL"),
                    help="SQLAlchemy URL (or set DATABASE_URL)")
    ap.add_argument("--out", default="schema.json", help="Output path")
    ap.add_argument("--sample-rows", type=int, default=1000,
                    help="Max rows sampled per table (default 1000)")
    ap.add_argument("--schemas", nargs="*",
                    help="Limit to these schemas (default: all user schemas)")
    args = ap.parse_args()

    if not args.url:
        ap.error("Provide --url or set DATABASE_URL env var")

    print(f"→ Connecting to {mask_url(args.url)}", file=sys.stderr)
    data = build_schema(args.url, sample_rows=args.sample_rows,
                        include_schemas=args.schemas)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)

    n_schemas = len(data["schemas"])
    n_tables = sum(len(s["tables"]) for s in data["schemas"])
    print(f"✓ Wrote {args.out}  ({n_schemas} schema(s), {n_tables} table(s))",
          file=sys.stderr)


if __name__ == "__main__":
    main()