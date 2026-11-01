"""Helpers to build WITH-clause queries."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CTESpec:
    name: str
    body_sql: str
    outer_sql: str
    body_tables: list[str] = field(default_factory=list)
    outer_tables: list[str] = field(default_factory=list)


def render_cte(spec: CTESpec) -> str:
    return f"WITH {spec.name} AS ({spec.body_sql}) {spec.outer_sql};"


def build_groupby_cte(cte_name, source_table, group_column, aggregate, agg_column=None, alias="n"):
    tbl = source_table.rsplit(".", 1)[1]
    grp = group_column.rsplit(".", 1)[1]
    if aggregate == "count":
        expr = f"COUNT(*) AS {alias}"
    elif aggregate in ("sum", "avg") and agg_column:
        col = agg_column.rsplit(".", 1)[1]
        expr = f"{aggregate.upper()}({col}) AS {alias}"
    else:
        raise ValueError(f"unsupported aggregate: {aggregate}")
    body = f"SELECT {grp}, {expr} FROM {tbl} GROUP BY {grp}"
    return body, alias