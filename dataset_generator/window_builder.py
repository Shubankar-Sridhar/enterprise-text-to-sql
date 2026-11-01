"""Helpers to build window-function fragments."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WindowSpec:
    select_expr: str
    alias: str
    partition_by: str
    order_by: str
    function: str


def build_rank_window(function, partition_column, order_column, order_dir="DESC", alias="rnk"):
    part = partition_column.rsplit(".", 1)[1]
    order = order_column.rsplit(".", 1)[1]
    expr = f"{function.upper()}() OVER (PARTITION BY {part} ORDER BY {order} {order_dir}) AS {alias}"
    return WindowSpec(
        select_expr=expr, alias=alias,
        partition_by=part, order_by=order, function=function,
    )