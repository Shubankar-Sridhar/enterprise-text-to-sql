"""Deterministic validation of business rules against the extracted schema."""
from __future__ import annotations

from collections import defaultdict

import sqlglot
from sqlglot.errors import ParseError

from .loader import BusinessRules, SchemaIndex


class ValidationError(Exception):
    pass


def validate(rules: BusinessRules, schema: SchemaIndex) -> list[str]:
    """Return a list of human-readable issues. Empty list == valid."""
    issues: list[str] = []

    # 1. Every entity key must exist as a table.
    for entity_key in rules.entities:
        if not schema.has_table(entity_key):
            issues.append(f"entity '{entity_key}' is not a table in schema.json")

    # 2. Every column rule key must exist as a column of its entity.
    for entity_key, ent in rules.entities.items():
        for col_key in ent.columns:
            if not schema.has_column(col_key):
                issues.append(f"column rule '{col_key}' is not a column in schema.json")
            elif not col_key.startswith(entity_key + "."):
                issues.append(
                    f"column rule '{col_key}' is not under entity '{entity_key}'"
                )

    # 3. rules_refs must point to a forbidden id or a metric/filter name.
    known_refs = (
        {f.id for f in rules.forbidden}
        | set(rules.metrics.keys())
        | set(rules.filters.keys())
    )
    for entity_key, ent in rules.entities.items():
        for ref in ent.rules_refs:
            if ref not in known_refs:
                issues.append(
                    f"entity '{entity_key}' references unknown rule '{ref}'"
                )

    # 4. Synonym collisions *within the same table*.
    per_table_synonyms: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for entity_key, ent in rules.entities.items():
        for syn in ent.synonyms:
            per_table_synonyms[entity_key][syn.lower()].append(entity_key)
        for col_key, col in ent.columns.items():
            for syn in col.synonyms:
                per_table_synonyms[entity_key][syn.lower()].append(col_key)

    for entity_key, syn_map in per_table_synonyms.items():
        for syn, owners in syn_map.items():
            if len(owners) > 1:
                issues.append(
                    f"synonym '{syn}' in {entity_key} is used by multiple columns: {owners}"
                )

    # 5. Cross-table synonym ambiguity must be declared in `ambiguities`.
    #    Only column-level synonyms participate; table-level synonyms and
    #    metric/filter synonyms are exempt (tables are scoped by name).
    declared_ambig = {k.lower() for k in rules.ambiguities.keys()}
    global_synonyms: dict[str, list[str]] = defaultdict(list)
    for entity_key, ent in rules.entities.items():
        for col_key, col in ent.columns.items():
            for syn in col.synonyms:
                global_synonyms[syn.lower()].append(col_key)
    for syn, owners in global_synonyms.items():
        tables = {o.rsplit(".", 1)[0] for o in owners}
        if len(tables) > 1 and syn not in declared_ambig:
            issues.append(
                f"cross-table synonym '{syn}' used by {owners} but not declared "
                f"in `ambiguities`"
            )

    # 6. Metrics / filters SQL must parse.
    for name, metric in rules.metrics.items():
        for field_name, frag in (
            ("definition_sql", metric.definition_sql),
            ("from_sql", metric.from_sql),
            ("where_sql", metric.where_sql),
        ):
            if frag:
                _try_parse(
                    frag,
                    dialect="postgres",
                    issues=issues,
                    where=f"metric '{name}.{field_name}'",
                    field_name=field_name,
                )
    for name, flt in rules.filters.items():
        _try_parse(
            flt.sql,
            dialect="postgres",
            issues=issues,
            where=f"filter '{name}'",
            field_name="sql",
        )

    return issues


def _try_parse(
    fragment: str,
    dialect: str,
    issues: list[str],
    where: str,
    field_name: str = "",
) -> None:
    """
    Try to parse a SQL fragment under several wrappings.

    Different fields in the rules file hold different kinds of fragments:
      - definition_sql: a scalar expression or an aggregate (e.g. "SUM(x)")
      - from_sql:       a FROM-clause body (e.g. "orders o JOIN … ON …")
      - where_sql:      a WHERE-clause body (e.g. "o.status = 'delivered'")
      - sql (filters):  a WHERE-clause body

    We wrap each in the smallest SELECT that makes it parseable.
    """
    stripped = fragment.strip()
    candidates: list[str] = []

    if field_name == "from_sql":
        # FROM fragment: needs a SELECT on top
        candidates.append(f"SELECT * FROM {stripped}")
    elif field_name in ("where_sql", "sql"):
        # WHERE fragment
        candidates.append(f"SELECT 1 WHERE {stripped}")
    elif field_name == "definition_sql":
        # Scalar or aggregate expression: appears after SELECT
        candidates.append(f"SELECT {stripped}")
        # Sometimes it's a full aggregate with FROM/WHERE already embedded,
        # e.g. a subquery metric. Try as-is.
        candidates.append(stripped)
    else:
        candidates.append(stripped)
        candidates.append(f"SELECT 1 WHERE {stripped}")
        candidates.append(f"SELECT * FROM {stripped}")

    for candidate in candidates:
        try:
            sqlglot.parse_one(candidate, read=dialect)
            return
        except ParseError:
            continue

    issues.append(f"{where}: could not parse as SQL: {fragment[:80]}…")