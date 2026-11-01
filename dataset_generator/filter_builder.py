"""Expand a named filter into a WHERE fragment."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FilterSQL:
    name: str
    where_sql: str
    synonyms: list[str]
    referenced_aliases: list[str]


def expand_filter(name: str, filter_def: dict) -> FilterSQL:
    sql = filter_def["sql"].strip()
    aliases = re.findall(r"\b([a-z]+\d*)\.", sql)
    return FilterSQL(
        name=name,
        where_sql=sql,
        synonyms=filter_def.get("synonyms", []),
        referenced_aliases=sorted(set(aliases)),
    )