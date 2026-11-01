"""Build a join graph from schema.json foreign keys; find shortest join paths."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class JoinEdge:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    fk_name: str


class JoinGraph:
    def __init__(self, schema: dict):
        self.edges: list[JoinEdge] = []
        self.adj: dict[str, list[JoinEdge]] = {}
        self._build(schema)

    def _build(self, schema: dict) -> None:
        for sch in schema.get("schemas", []):
            sname = sch["name"]
            for tbl in sch.get("tables", []):
                tkey = f"{sname}.{tbl['name']}"
                self.adj.setdefault(tkey, [])
                for fk in tbl.get("foreign_keys", []):
                    if fk["referred_schema"] != sname:
                        continue
                    ref_tkey = f"{fk['referred_schema']}.{fk['referred_table']}"
                    for local_col, ref_col in zip(
                        fk["constrained_columns"], fk["referred_columns"]
                    ):
                        edge = JoinEdge(
                            left_table=ref_tkey,
                            left_column=ref_col,
                            right_table=tkey,
                            right_column=local_col,
                            fk_name=fk["name"],
                        )
                        self.edges.append(edge)
                        self.adj.setdefault(ref_tkey, []).append(edge)
                        self.adj.setdefault(tkey, []).append(
                            JoinEdge(
                                left_table=tkey,
                                left_column=local_col,
                                right_table=ref_tkey,
                                right_column=ref_col,
                                fk_name=fk["name"],
                            )
                        )

    def path(self, start: str, end: str, max_hops: int = 3) -> list[JoinEdge] | None:
        if start == end:
            return []
        visited = {start}
        queue: deque[tuple[str, list[JoinEdge]]] = deque([(start, [])])
        while queue:
            node, path = queue.popleft()
            if len(path) >= max_hops:
                continue
            for edge in self.adj.get(node, []):
                nxt = edge.right_table
                new_path = path + [edge]
                if nxt == end:
                    return new_path
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, new_path))
        return None

    def reachable_within(self, start: str, hops: int) -> list[str]:
        out = []
        seen = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        while queue:
            node, d = queue.popleft()
            if d >= hops:
                continue
            for edge in self.adj.get(node, []):
                nxt = edge.right_table
                if nxt not in seen:
                    seen.add(nxt)
                    out.append(nxt)
                    queue.append((nxt, d + 1))
        return out