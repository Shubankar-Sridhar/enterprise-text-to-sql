"""Load schema.json and business_rules.yaml; resolve every reference."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic models — these define the contract of business_rules.yaml
# ---------------------------------------------------------------------------

class ColumnRule(BaseModel):
    purpose: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    value_map: dict[str, list[str]] = Field(default_factory=dict)
    notes: str | None = None


class EntityRule(BaseModel):
    purpose: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    rules_refs: list[str] = Field(default_factory=list)
    columns: dict[str, ColumnRule] = Field(default_factory=dict)


class MetricRule(BaseModel):
    definition_sql: str
    from_sql: str | None = None
    where_sql: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    notes: str | None = None


class FilterRule(BaseModel):
    sql: str
    synonyms: list[str] = Field(default_factory=list)


class ForbiddenRule(BaseModel):
    id: str
    rule: str
    applies_to: list[str] = Field(default_factory=list)


class AmbiguityRule(BaseModel):
    candidates: list[str]
    disambiguation: str


class BusinessRules(BaseModel):
    version: str = "1.0"
    domain: str = "unspecified"
    entities: dict[str, EntityRule] = Field(default_factory=dict)
    metrics: dict[str, MetricRule] = Field(default_factory=dict)
    filters: dict[str, FilterRule] = Field(default_factory=dict)
    forbidden: list[ForbiddenRule] = Field(default_factory=list)
    ambiguities: dict[str, AmbiguityRule] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schema index — a fast lookup of every fully-qualified name in schema.json
# ---------------------------------------------------------------------------

class SchemaIndex:
    def __init__(self, schema_doc: dict[str, Any]):
        self.tables: dict[str, dict] = {}       # "public.orders" -> table dict
        self.columns: dict[str, dict] = {}      # "public.orders.order_status" -> column dict
        self._index(schema_doc)

    def _index(self, doc: dict[str, Any]) -> None:
        for sch in doc.get("schemas", []):
            sname = sch["name"]
            for tbl in sch.get("tables", []):
                tkey = f"{sname}.{tbl['name']}"
                self.tables[tkey] = tbl
                for col in tbl.get("columns", []):
                    ckey = f"{tkey}.{col['name']}"
                    self.columns[ckey] = col

    def has_table(self, key: str) -> bool:
        return key in self.tables

    def has_column(self, key: str) -> bool:
        return key in self.columns


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_schema(schema_path: Path) -> tuple[dict[str, Any], SchemaIndex]:
    doc = json.loads(schema_path.read_text(encoding="utf-8"))
    return doc, SchemaIndex(doc)


def load_rules(rules_path: Path) -> BusinessRules:
    raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    return BusinessRules.model_validate(raw)