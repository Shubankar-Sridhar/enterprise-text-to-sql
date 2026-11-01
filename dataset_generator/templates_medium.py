"""Medium-tier templates: joins, group-by, metrics, filters."""
from __future__ import annotations

import re
from typing import Any

from .templates import SlotBinding, Template
from .join_graph import JoinGraph
from .metric_builder import expand_metric, MetricSQL
from .filter_builder import expand_filter, FilterSQL


def render_join_path(start_table: str, edges: list, start_alias: str = "t0") -> tuple[str, dict[str, str]]:
    aliases = {start_table: start_alias}
    from_sql = f"{start_table.rsplit('.', 1)[1]} {start_alias}"
    current = start_table
    for i, edge in enumerate(edges):
        nxt = edge.right_table
        if nxt not in aliases:
            aliases[nxt] = f"t{i+1}"
        alias = aliases[nxt]
        from_sql += (
            f" JOIN {nxt.rsplit('.', 1)[1]} {alias}"
            f" ON {alias}.{edge.right_column} = {aliases[current]}.{edge.left_column}"
        )
        current = nxt
    return from_sql, aliases


def _edge_from_dict(d: dict):
    from .join_graph import JoinEdge
    return JoinEdge(**d)


def _rewrite_filter_aliases(where_sql: str, target_aliases: dict[str, str]) -> str:
    def repl(match):
        return match.group(0)
    return re.sub(r"\b([a-z]+\d*)\.(\w+)", repl, where_sql)


# ---------------------------------------------------------------------------
# T5: two-table join + count
# ---------------------------------------------------------------------------

class JoinCount(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T5_join_count",
            description="Count rows in table A joined to table B",
            slots=["table_a", "table_b"],
            difficulty="medium",
            tags=["two_table", "join", "aggregate", "count"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        other = b.value.get("other_table") if isinstance(b.value, dict) else None
        return f"T5::{b.table}::{other}"

    def enumerate_bindings(self, table, table_meta, context):
        for other in self.graph.reachable_within(table, hops=1):
            if other == table:
                continue
            if (other, table) < (table, other):
                continue
            path = self.graph.path(table, other, max_hops=1)
            if not path:
                continue
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=None,
                value={"other_table": other, "path": [e.__dict__ for e in path]},
                aggregate="count",
                synonym_used=None,
                context_refs=["fk"],
            )

    def build_sql(self, b):
        other = b.value["other_table"]
        path = [_edge_from_dict(e) for e in b.value["path"]]
        from_sql, _ = render_join_path(b.table, path)
        return f"SELECT COUNT(*) AS n FROM {from_sql};"

    def realize_brief(self, b):
        return {"intent": "count records across two related entities"}


# ---------------------------------------------------------------------------
# T6: two-table join + count filtered
# ---------------------------------------------------------------------------

class JoinFilterCount(Template):
    def __init__(self, join_graph: JoinGraph, filters: dict[str, dict]):
        super().__init__(
            id="T6_join_filter_count",
            description="Count joined rows with a named filter",
            slots=["table_a", "table_b", "filter"],
            difficulty="medium",
            tags=["two_table", "join", "aggregate", "count", "time_filter"],
        )
        self.graph = join_graph
        self.filters = filters

    def split_group_key(self, b):
        return f"T6::{b.table}::{b.value.get('filter_name') if isinstance(b.value, dict) else ''}"

    def enumerate_bindings(self, table, table_meta, context):
        # Only emit once per (primary, partner) pair. Anchor on orders to keep
        # the SQL simple and correct.
        if table != "public.orders":
            return
        partners = [p for p in self.graph.reachable_within(table, hops=1) if p != table]
        partners.sort()
        if not partners:
            return
        partner = partners[0]
        for filter_name, filter_def in self.filters.items():
            flt = expand_filter(filter_name, filter_def)
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=None,
                value={
                    "other_table": partner,
                    "filter_name": filter_name,
                    "filter_where": flt.where_sql,
                },
                aggregate="count",
                synonym_used=(flt.synonyms[0] if flt.synonyms else None),
                context_refs=["fk", "filter"],
            )

    def build_sql(self, b):
        other = b.value["other_table"]
        path = self.graph.path(b.table, other, max_hops=1) or []
        from_sql, aliases = render_join_path(b.table, path)
        return f"SELECT COUNT(*) AS n FROM {from_sql} WHERE {b.value['filter_where']};"

    def realize_brief(self, b):
        return {
            "intent": "count joined records filtered by time",
            "filter_name": b.value.get("filter_name"),
            "filter_synonym": b.synonym_used,
        }


# ---------------------------------------------------------------------------
# T7: group-by + count
# ---------------------------------------------------------------------------

class GroupByCount(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T7_group_by_count",
            description="Count rows grouped by a categorical column",
            slots=["table", "group_column"],
            difficulty="medium",
            tags=["single_table", "aggregate", "count", "group_by"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T7::column::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            vmap = col_ctx.get("value_map") or {}
            if not vmap or len(vmap) > 10:
                continue
            synonyms = col_ctx.get("synonyms") or []
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=col_key,
                value=None,
                aggregate="count",
                synonym_used=synonyms[0] if synonyms else None,
                context_refs=["value_map"],
            )

    def build_sql(self, b):
        col_name = b.column.rsplit(".", 1)[1]
        tbl_name = b.table.rsplit(".", 1)[1]
        return (
            f"SELECT {col_name}, COUNT(*) AS n FROM {tbl_name} "
            f"GROUP BY {col_name} ORDER BY n DESC;"
        )

    def realize_brief(self, b):
        return {
            "intent": "count rows grouped by a category",
            "group_column_synonym": b.synonym_used,
        }


# ---------------------------------------------------------------------------
# T8: metric reference
# ---------------------------------------------------------------------------

class MetricQuery(Template):
    def __init__(self, join_graph: JoinGraph, metrics: dict[str, dict]):
        super().__init__(
            id="T8_metric_query",
            description="Compute a business metric",
            slots=["metric"],
            difficulty="medium",
            tags=["metric", "aggregate", "rule_reference"],
        )
        self.graph = join_graph
        self.metrics = metrics

    def split_group_key(self, b):
        return f"T8::metric::{b.value.get('metric_name') if isinstance(b.value, dict) else ''}"

    def enumerate_bindings(self, table, table_meta, context):
        # Only emit once, on the first table
        if table != sorted(context["tables"].keys())[0]:
            return
        for metric_name, metric_def in self.metrics.items():
            for syn in (metric_def.get("synonyms") or [metric_name]):
                yield SlotBinding(
                    template_id=self.id,
                    table=table,
                    column=None,
                    value={"metric_name": metric_name},
                    aggregate=None,
                    synonym_used=syn,
                    context_refs=["metric"],
                )

    def build_sql(self, b):
        metric = expand_metric(b.value["metric_name"], self.metrics[b.value["metric_name"]])
        where = f" WHERE {metric.where_sql}" if metric.where_sql else ""
        return f"SELECT {metric.select_expr} AS result FROM {metric.from_sql}{where};"

    def realize_brief(self, b):
        return {
            "intent": "compute a business metric",
            "metric_synonym": b.synonym_used,
            "metric_name": b.value.get("metric_name"),
        }


# ---------------------------------------------------------------------------
# T9: metric + filter
# ---------------------------------------------------------------------------

class MetricWithFilter(Template):
    def __init__(self, join_graph: JoinGraph, metrics: dict[str, dict], filters: dict[str, dict]):
        super().__init__(
            id="T9_metric_with_filter",
            description="Compute a metric restricted by a named filter",
            slots=["metric", "filter"],
            difficulty="medium",
            tags=["metric", "filter", "rule_reference"],
        )
        self.graph = join_graph
        self.metrics = metrics
        self.filters = filters

    def split_group_key(self, b):
        return f"T9::{b.value.get('metric_name') if isinstance(b.value, dict) else ''}"

    def enumerate_bindings(self, table, table_meta, context):
        if table != sorted(context["tables"].keys())[0]:
            return
        for metric_name, metric_def in self.metrics.items():
            metric = expand_metric(metric_name, metric_def)
            for filter_name, filter_def in self.filters.items():
                flt = expand_filter(filter_name, filter_def)
                # Only combine if filter's aliases intersect metric's
                if not (set(metric.join_aliases.values()) & set(flt.referenced_aliases)):
                    continue
                # Emit ONE record per (metric, filter) pair, not one per synonym.
                msyn = (metric_def.get("synonyms") or [metric_name])[0]
                yield SlotBinding(
                    template_id=self.id,
                    table=table,
                    column=None,
                    value={
                        "metric_name": metric_name,
                        "filter_name": filter_name,
                    },
                    aggregate=None,
                    synonym_used=msyn,
                    context_refs=["metric", "filter"],
                )

    def build_sql(self, b):
        metric = expand_metric(b.value["metric_name"], self.metrics[b.value["metric_name"]])
        flt = expand_filter(b.value["filter_name"], self.filters[b.value["filter_name"]])
        clauses = [c for c in (metric.where_sql, flt.where_sql) if c]
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return f"SELECT {metric.select_expr} AS result FROM {metric.from_sql}{where};"

    def realize_brief(self, b):
        return {
            "intent": "compute a business metric restricted by a time window",
            "metric_synonym": b.synonym_used,
            "filter_name": b.value.get("filter_name"),
        }