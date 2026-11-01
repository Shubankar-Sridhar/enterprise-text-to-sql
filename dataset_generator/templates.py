"""Template registry. Each template knows how to:
   1. enumerate its slot bindings from context.json
   2. emit a deterministic SQL string
   3. describe itself to the LLM realizer (without leaking SQL)
   4. declare a split-grouping key so related records stay together
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class SlotBinding:
    template_id: str
    table: str
    column: str | None
    value: Any | None
    aggregate: str | None
    synonym_used: str | None
    context_refs: list[str] = field(default_factory=list)


@dataclass
class Template:
    id: str
    description: str
    slots: list[str]
    difficulty: str = "easy"
    tags: list[str] = field(default_factory=list)

    def enumerate_bindings(self, table, table_meta, context) -> Iterator[SlotBinding]:
        raise NotImplementedError

    def build_sql(self, binding: SlotBinding) -> str:
        raise NotImplementedError

    def realize_brief(self, binding: SlotBinding) -> dict[str, Any]:
        raise NotImplementedError

    def split_group_key(self, binding: SlotBinding) -> str:
        return f"{self.id}::{binding.table}::{binding.column}::{binding.value}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_aliases(aliases) -> list:
    if aliases is None:
        return [None]
    if isinstance(aliases, str):
        return [aliases] if aliases else [None]
    if isinstance(aliases, (list, tuple)):
        cleaned = [a for a in aliases if isinstance(a, str) and a]
        return cleaned or [None]
    return [None]


def _escape(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace("'", "''")


# ---------------------------------------------------------------------------
# T1: list rows filtered by categorical value
# ---------------------------------------------------------------------------

class FilterByCategory(Template):
    def __init__(self):
        super().__init__(
            id="T1_filter_by_category",
            description="Select rows from one table where a categorical column equals a value",
            slots=["table", "column", "value"],
            tags=["single_table", "filter", "categorical"],
        )

    def split_group_key(self, binding):
        return f"T1::column::{binding.table}::{binding.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            vmap = col_ctx.get("value_map") or {}
            if not vmap or len(vmap) > 10:
                continue
            for raw_value, aliases in vmap.items():
                for alias in _normalize_aliases(aliases):
                    yield SlotBinding(
                        template_id=self.id,
                        table=table,
                        column=col_key,
                        value=raw_value,
                        aggregate=None,
                        synonym_used=alias,
                        context_refs=["value_map"],
                    )

    def build_sql(self, b):
        col_name = b.column.rsplit(".", 1)[1]
        tbl_name = b.table.rsplit(".", 1)[1]
        return f"SELECT * FROM {tbl_name} WHERE {col_name} = '{_escape(b.value)}';"

    def realize_brief(self, b):
        return {
            "intent": "list rows matching a category",
            "filter_value_synonym": b.synonym_used,
            "raw_value": b.value,
        }


# ---------------------------------------------------------------------------
# T2: count rows filtered by categorical value
# ---------------------------------------------------------------------------

class CountByCategory(Template):
    def __init__(self):
        super().__init__(
            id="T2_count_by_category",
            description="Count rows in a table where a categorical column equals a value",
            slots=["table", "column", "value"],
            tags=["single_table", "aggregate", "count", "categorical"],
        )

    def split_group_key(self, binding):
        return f"T2::column::{binding.table}::{binding.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            vmap = col_ctx.get("value_map") or {}
            if not vmap or len(vmap) > 10:
                continue
            for raw_value, aliases in vmap.items():
                for alias in _normalize_aliases(aliases):
                    yield SlotBinding(
                        template_id=self.id,
                        table=table,
                        column=col_key,
                        value=raw_value,
                        aggregate="count",
                        synonym_used=alias,
                        context_refs=["value_map"],
                    )

    def build_sql(self, b):
        col_name = b.column.rsplit(".", 1)[1]
        tbl_name = b.table.rsplit(".", 1)[1]
        return f"SELECT COUNT(*) AS n FROM {tbl_name} WHERE {col_name} = '{_escape(b.value)}';"

    def realize_brief(self, b):
        return {
            "intent": "count rows matching a category",
            "filter_value_synonym": b.synonym_used,
            "raw_value": b.value,
        }


# ---------------------------------------------------------------------------
# T3: aggregate a numeric column
# ---------------------------------------------------------------------------

class AggregateNumeric(Template):
    SUPPORTED_AGGS = ("avg", "sum", "min", "max")

    def __init__(self):
        super().__init__(
            id="T3_aggregate_numeric",
            description="Apply an aggregate to one numeric column",
            slots=["table", "column", "aggregate"],
            tags=["single_table", "aggregate", "numeric"],
        )

    def split_group_key(self, binding):
        return f"T3::column::{binding.table}::{binding.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col in table_meta.get("columns", []):
            col_type = (col.get("type") or "").upper()
            if not any(t in col_type for t in ("NUMERIC", "INTEGER", "BIGINT", "DECIMAL")):
                continue
            if col.get("primary_key"):
                continue
            col_key = f"{table}.{col['name']}"
            # Optional per-column aggregate whitelist from context
            col_ctx = ctx_table["columns"].get(col_key, {})
            allowed = col_ctx.get("numeric_aggregates")
            aggs = self.SUPPORTED_AGGS if not allowed else tuple(allowed)
            for agg in aggs:
                if agg not in self.SUPPORTED_AGGS:
                    continue
                yield SlotBinding(
                    template_id=self.id,
                    table=table,
                    column=col_key,
                    value=None,
                    aggregate=agg,
                    synonym_used=None,
                    context_refs=["column"],
                )

    def build_sql(self, b):
        col_name = b.column.rsplit(".", 1)[1]
        tbl_name = b.table.rsplit(".", 1)[1]
        return f"SELECT {b.aggregate.upper()}({col_name}) AS result FROM {tbl_name};"

    def realize_brief(self, b):
        return {
            "intent": f"{b.aggregate} a numeric field",
            "aggregate": b.aggregate,
        }


# ---------------------------------------------------------------------------
# T4: distinct count of a column
# ---------------------------------------------------------------------------

class DistinctCount(Template):
    def __init__(self):
        super().__init__(
            id="T4_distinct_count",
            description="Count distinct values of a column",
            slots=["table", "column"],
            tags=["single_table", "aggregate", "distinct"],
        )

    def split_group_key(self, binding):
        return f"T4::column::{binding.table}::{binding.column}"

    def enumerate_bindings(self, table, table_meta, context):
        ctx_table = context["tables"].get(table)
        if not ctx_table:
            return
        for col_key, col_ctx in ctx_table["columns"].items():
            if not col_ctx.get("synonyms"):
                continue
            if col_ctx.get("value_map"):
                continue
            synonyms = _normalize_aliases(col_ctx.get("synonyms"))
            yield SlotBinding(
                template_id=self.id,
                table=table,
                column=col_key,
                value=None,
                aggregate="count_distinct",
                synonym_used=synonyms[0] if synonyms else None,
                context_refs=["synonyms"],
            )

    def build_sql(self, b):
        col_name = b.column.rsplit(".", 1)[1]
        tbl_name = b.table.rsplit(".", 1)[1]
        return f"SELECT COUNT(DISTINCT {col_name}) AS n FROM {tbl_name};"

    def realize_brief(self, b):
        return {
            "intent": "count distinct values",
            "aggregate": "count_distinct",
            "column_synonym": b.synonym_used,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def build_registry(schema: dict, context: dict) -> dict[str, Template]:
    """Build every template. Medium/hard templates are imported lazily so that
    easy-only operation still works if those modules are missing."""
    easy = [FilterByCategory(), CountByCategory(), AggregateNumeric(), DistinctCount()]

    medium: list[Template] = []
    hard: list[Template] = []
    try:
        from .join_graph import JoinGraph
        from .templates_medium import (
            JoinCount,
            JoinFilterCount,
            GroupByCount,
            MetricQuery,
            MetricWithFilter,
        )
        graph = JoinGraph(schema)
        metrics = context.get("metrics", {}) or {}
        filters = context.get("filters", {}) or {}
        medium = [
            JoinCount(graph),
            JoinFilterCount(graph, filters),
            GroupByCount(graph),
            MetricQuery(graph, metrics),
            MetricWithFilter(graph, metrics, filters),
        ]

        from .ambiguity_binder import enumerate_ambiguity_bindings
        from .templates_hard import (
            TopNByAggregate,
            ThresholdCTE,
            AntiJoinExists,
            TwoHopJoinAggregate,
            MetricWithJoinConstraint,
            SetUnion,
            AmbiguityStress,
            RunningTotal,
        )
        ambiguities = enumerate_ambiguity_bindings(context)
        hard = [
            TopNByAggregate(graph),
            ThresholdCTE(graph),
            AntiJoinExists(graph),
            TwoHopJoinAggregate(graph),
            MetricWithJoinConstraint(graph, metrics, context),
            SetUnion(graph),
            AmbiguityStress(graph, ambiguities),
            RunningTotal(graph),
        ]
    except ImportError as e:
        import sys
        print(f"⚠ medium/hard templates not loaded: {e}", file=sys.stderr)

    return {t.id: t for t in easy + medium + hard}


REGISTRY: dict[str, Template] = {
    t.id: t for t in [
        FilterByCategory(),
        CountByCategory(),
        AggregateNumeric(),
        DistinctCount(),
    ]
}