"""Hard-tier templates: subqueries, CTEs, window functions, ambiguity."""
from __future__ import annotations

from .templates import SlotBinding, Template
from .join_graph import JoinGraph
from .metric_builder import expand_metric
from .cte_builder import CTESpec, render_cte, build_groupby_cte
from .templates_medium import render_join_path, _edge_from_dict


class TopNByAggregate(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T10_top_n_by_aggregate",
            description="Rank groups by an aggregate and take the top N",
            slots=["table", "group_column"],
            difficulty="hard",
            tags=["window", "rank", "aggregate"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T10::column::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            vmap = col_ctx.get("value_map") or {}
            if not vmap or len(vmap) > 15:
                continue
            synonyms = col_ctx.get("synonyms") or []
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=col_key,
                value={"top_n": 3},
                aggregate="count",
                synonym_used=synonyms[0] if synonyms else None,
                context_refs=["value_map"],
            )

    def build_sql(self, b):
        tbl = b.table.rsplit(".", 1)[1]
        col = b.column.rsplit(".", 1)[1]
        n = b.value["top_n"]
        return (
            f"WITH agg AS (SELECT {col}, COUNT(*) AS n FROM {tbl} GROUP BY {col}) "
            f"SELECT {col}, n, RANK() OVER (ORDER BY n DESC) AS rnk "
            f"FROM agg ORDER BY n DESC LIMIT {n};"
        )

    def realize_brief(self, b):
        return {
            "intent": f"top {b.value['top_n']} categories by count",
            "group_column_synonym": b.synonym_used,
            "top_n": b.value["top_n"],
        }


class ThresholdCTE(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T11_threshold_cte",
            description="Groups whose count exceeds a threshold",
            slots=["table", "group_column"],
            difficulty="hard",
            tags=["cte", "aggregate", "threshold"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T11::column::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col in table_meta.get("columns", []):
            col_name = col["name"]
            if not (col_name.endswith("_id") or col_name.endswith("_unique_id")):
                continue
            if col.get("primary_key"):
                continue
            col_key = f"{table}.{col['name']}"
            for threshold in (3, 5):
                yield SlotBinding(
                    template_id=self.id,
                    table=table,
                    column=col_key,
                    value={"threshold": threshold},
                    aggregate="count",
                    synonym_used=None,
                    context_refs=["column"],
                )

    def build_sql(self, b):
        col = b.column.rsplit(".", 1)[1]
        t = b.value["threshold"]
        body, _ = build_groupby_cte(
            "per_group", b.table, b.column, "count", alias="n",
        )
        spec = CTESpec(
            name="per_group",
            body_sql=body,
            outer_sql=f"SELECT {col}, n FROM per_group WHERE n > {t} ORDER BY n DESC",
        )
        return render_cte(spec)

    def realize_brief(self, b):
        return {
            "intent": f"groups whose count exceeds {b.value['threshold']}",
            "threshold": b.value["threshold"],
        }


class AntiJoinExists(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T12_anti_join_exists",
            description="Entities with no related child rows",
            slots=["outer_table", "outer_column", "inner_table", "inner_column"],
            difficulty="hard",
            tags=["subquery", "not_exists", "anti_join"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T12::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        for edge in self.graph.edges:
            if edge.left_table != table:
                continue
            yield SlotBinding(
                template_id=self.id,
                table=edge.left_table,
                # Fully-qualified so downstream code can rsplit safely
                column=f"{edge.left_table}.{edge.left_column}",
                value={
                    "outer_col": edge.left_column,       # bare
                    "inner_table": edge.right_table,
                    "inner_col": edge.right_column,      # bare
                    "fk_name": edge.fk_name,
                },
                aggregate=None,
                synonym_used=None,
                context_refs=["fk"],
            )

    def build_sql(self, b):
        outer_tbl = b.table.rsplit(".", 1)[1]
        outer_col = b.value["outer_col"]
        inner_tbl = b.value["inner_table"].rsplit(".", 1)[1]
        inner_col = b.value["inner_col"]
        return (
            f"SELECT {outer_col} FROM {outer_tbl} t "
            f"WHERE NOT EXISTS ("
            f"SELECT 1 FROM {inner_tbl} i WHERE i.{inner_col} = t.{outer_col}"
            f");"
        )

    def realize_brief(self, b):
        return {"intent": "records with no related child rows"}


class TwoHopJoinAggregate(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T13_two_hop_aggregate",
            description="Count across a three-table join path",
            slots=["start_table", "end_table"],
            difficulty="hard",
            tags=["three_table", "join", "aggregate"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        end = b.value.get("end_table") if isinstance(b.value, dict) else None
        return f"T13::{b.table}::{end}"

    def enumerate_bindings(self, table, table_meta, context):
        for other in self.graph.reachable_within(table, hops=2):
            if other == table:
                continue
            if (other, table) < (table, other):
                continue
            path = self.graph.path(table, other, max_hops=2)
            if not path or len(path) != 2:
                continue
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=None,
                value={
                    "end_table": other,
                    "path": [e.__dict__ for e in path],
                },
                aggregate="count",
                synonym_used=None,
                context_refs=["fk"],
            )

    def build_sql(self, b):
        path = [_edge_from_dict(e) for e in b.value["path"]]
        from_sql, _ = render_join_path(b.table, path)
        return f"SELECT COUNT(*) AS n FROM {from_sql};"

    def realize_brief(self, b):
        return {"intent": "count across three related entities"}


class MetricWithJoinConstraint(Template):
    def __init__(self, join_graph: JoinGraph, metrics: dict, context: dict):
        super().__init__(
            id="T14_metric_with_join_constraint",
            description="Compute a metric restricted by a joined-table column",
            slots=["metric", "constraint_column", "constraint_value"],
            difficulty="hard",
            tags=["metric", "join", "constraint"],
        )
        self.graph = join_graph
        self.metrics = metrics
        self.context = context

    def split_group_key(self, b):
        return f"T14::{b.value.get('metric_name') if isinstance(b.value, dict) else ''}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        if table != sorted(context["tables"].keys())[0]:
            return
        for metric_name, metric_def in self.metrics.items():
            metric = expand_metric(metric_name, metric_def)
            for tkey in sorted(metric.join_aliases.keys()):
                tctx = context["tables"].get(tkey)
                if not tctx:
                    continue
                for col_key, col_ctx in tctx["columns"].items():
                    vmap = col_ctx.get("value_map") or {}
                    if not vmap or len(vmap) > 10:
                        continue
                    # Emit ONE record per (metric, categorical column),
                    # not one per value. Pick the first value as representative.
                    raw_value, aliases = next(iter(vmap.items()))
                    alias = aliases[0] if isinstance(aliases, list) and aliases else raw_value
                    yield SlotBinding(
                        template_id=self.id,
                        table=tkey,
                        column=col_key,
                        value={
                            "metric_name": metric_name,
                            "raw_value": raw_value,
                        },
                        aggregate=None,
                        synonym_used=alias,
                        context_refs=["metric", "column"],
                    )

    def build_sql(self, b):
        metric = expand_metric(b.value["metric_name"], self.metrics[b.value["metric_name"]])
        alias = metric.join_aliases.get(b.table)
        if not alias:
            return f"SELECT {metric.select_expr} AS result FROM {metric.from_sql};"
        constraint_col = b.column.rsplit(".", 1)[1]
        literal = str(b.value["raw_value"]).replace("'", "''")
        clauses = [c for c in (metric.where_sql,) if c]
        clauses.append(f"{alias}.{constraint_col} = '{literal}'")
        where = " WHERE " + " AND ".join(clauses)
        return f"SELECT {metric.select_expr} AS result FROM {metric.from_sql}{where};"

    def realize_brief(self, b):
        return {
            "intent": "compute a metric restricted by a category",
            "metric_synonym": b.value.get("metric_name"),
            "filter_value_synonym": b.synonym_used,
        }


class SetUnion(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T15_set_union",
            description="Union of two filtered selects on the same table",
            slots=["table", "column", "value_a", "value_b"],
            difficulty="hard",
            tags=["set_op", "union"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T15::column::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            vmap = col_ctx.get("value_map") or {}
            if not vmap or len(vmap) < 2 or len(vmap) > 10:
                continue
            values = list(vmap.items())
            (va, aliases_a), (vb, aliases_b) = values[0], values[1]
            alias_a = aliases_a[0] if isinstance(aliases_a, list) and aliases_a else va
            alias_b = aliases_b[0] if isinstance(aliases_b, list) and aliases_b else vb
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=col_key,
                value={
                    "value_a": va, "value_b": vb,
                    "alias_a": alias_a, "alias_b": alias_b,
                },
                aggregate=None,
                synonym_used=None,
                context_refs=["value_map"],
            )

    def build_sql(self, b):
        tbl = b.table.rsplit(".", 1)[1]
        col = b.column.rsplit(".", 1)[1]
        va = str(b.value["value_a"]).replace("'", "''")
        vb = str(b.value["value_b"]).replace("'", "''")
        return (
            f"SELECT * FROM {tbl} WHERE {col} = '{va}' "
            f"UNION "
            f"SELECT * FROM {tbl} WHERE {col} = '{vb}';"
        )

    def realize_brief(self, b):
        return {
            "intent": "records matching either of two categories",
            "filter_value_synonym": b.value["alias_a"],
            "raw_value": b.value["value_a"],
        }


class AmbiguityStress(Template):
    def __init__(self, join_graph: JoinGraph, ambiguity_bindings: list):
        super().__init__(
            id="T16_ambiguity_stress",
            description="Questions resolved by an ambiguity rule",
            slots=["term", "table", "column"],
            difficulty="hard",
            tags=["ambiguity", "disambiguation", "stress_test"],
        )
        self.graph = join_graph
        self.ambiguity_bindings = ambiguity_bindings

    def split_group_key(self, b):
        return f"T16::term::{b.value.get('term') if isinstance(b.value, dict) else ''}"

    def enumerate_bindings(self, table, table_meta, context):
        for amb in self.ambiguity_bindings:
            if not amb.chosen.startswith(table + "."):
                continue
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=amb.chosen,
                value={
                    "term": amb.term,
                    "rule": amb.disambiguation_rule,
                    "rationale": amb.rationale,
                    "candidates": amb.candidates,
                },
                aggregate=None,
                synonym_used=amb.term,
                context_refs=["ambiguity"],
            )

    def build_sql(self, b):
        tbl = b.table.rsplit(".", 1)[1]
        col = b.column.rsplit(".", 1)[1]
        return f"SELECT DISTINCT {col} FROM {tbl} ORDER BY {col};"

    def realize_brief(self, b):
        return {
            "intent": "list distinct values of an ambiguous term",
            "ambiguous_term": b.value.get("term"),
            "disambiguation_rule": b.value.get("rule"),
        }


class RunningTotal(Template):
    def __init__(self, join_graph: JoinGraph):
        super().__init__(
            id="T17_running_total",
            description="Cumulative sum over a time-ordered partition",
            slots=["table", "sum_column", "partition_column", "order_column"],
            difficulty="hard",
            tags=["window", "sum_over", "temporal"],
        )
        self.graph = join_graph

    def split_group_key(self, b):
        return f"T17::column::{b.table}::{b.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        numeric_cols = [
            c for c in table_meta["columns"]
            if "NUMERIC" in (c.get("type") or "").upper()
            or "INTEGER" in (c.get("type") or "").upper()
        ]
        temporal_cols = [
            c for c in table_meta["columns"]
            if "TIMESTAMP" in (c.get("type") or "").upper()
            or "DATE" in (c.get("type") or "").upper()
        ]
        id_cols = [
            c for c in table_meta["columns"]
            if c["name"].endswith("_id") and not c.get("primary_key")
        ]
        if not (numeric_cols and temporal_cols and id_cols):
            return
        num = numeric_cols[0]
        ts = temporal_cols[0]
        pk = id_cols[0]
        yield SlotBinding(
            template_id=self.id,
            table=table,
            column=f"{table}.{num['name']}",
            value={
                "partition_column": f"{table}.{pk['name']}",
                "order_column": f"{table}.{ts['name']}",
            },
            aggregate="sum_over",
            synonym_used=None,
            context_refs=["column"],
        )

    def build_sql(self, b):
        tbl = b.table.rsplit(".", 1)[1]
        sum_col = b.column.rsplit(".", 1)[1]
        part_col = b.value["partition_column"].rsplit(".", 1)[1]
        order_col = b.value["order_column"].rsplit(".", 1)[1]
        return (
            f"SELECT {part_col}, {order_col}, {sum_col}, "
            f"SUM({sum_col}) OVER (PARTITION BY {part_col} ORDER BY {order_col}) "
            f"AS running_total FROM {tbl} ORDER BY {part_col}, {order_col};"
        )

    def realize_brief(self, b):
        return {"intent": "running total per group over time"}