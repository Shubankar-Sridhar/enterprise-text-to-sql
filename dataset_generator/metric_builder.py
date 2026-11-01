"""Expand a metric definition into a SELECT fragment + FROM + WHERE."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MetricSQL:
    name: str
    select_expr: str
    from_sql: str
    where_sql: str | None
    primary_table_alias: str
    join_aliases: dict[str, str]


def expand_metric(name: str, metric: dict) -> MetricSQL:
    from_sql = (metric.get("from_sql") or "").strip()
    where_sql = (metric.get("where_sql") or "").strip() or None
    select_expr = metric["definition_sql"].strip()

    aliases: dict[str, str] = {}
    primary_alias = "t"
    if from_sql:
        m = re.match(r"(\w+)\s+(\w+)", from_sql)
        if m:
            aliases[f"public.{m.group(1)}"] = m.group(2)
            primary_alias = m.group(2)
        else:
            first = from_sql.split()[0]
            aliases[f"public.{first}"] = first
            primary_alias = first

    for m in re.finditer(r"JOIN\s+(\w+)\s+(\w+)", from_sql):
        aliases[f"public.{m.group(1)}"] = m.group(2)

    return MetricSQL(
        name=name,
        select_expr=select_expr,
        from_sql=from_sql,
        where_sql=where_sql,
        primary_table_alias=primary_alias,
        join_aliases=aliases,
    )