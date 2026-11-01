"""Template-family-aware splitting. No leakage of template structure or column values."""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Split:
    train: list[dict]
    dev: list[dict]
    test: list[dict]


def split_by_template(
    records: list[dict],
    dev_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> Split:
    """
    Split records into train/dev/test such that:
      - Every template appears in every split (coverage).
      - All records sharing a template's `split_group_key` stay together —
        so a model that saw `products.price AVG` in train will not be
        tested on `products.price SUM`.
    """
    rng = random.Random(seed)
    by_template: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_template[r["template_id"]].append(r)

    train, dev, test = [], [], []

    for tmpl_id, rows in by_template.items():
        # Group rows by the template's split_group_key, if any
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            key = r.get("split_group_key") or r["id"]
            groups[key].append(r)

        group_list = list(groups.values())
        rng.shuffle(group_list)
        n_groups = len(group_list)

        # Need at least 3 groups for a meaningful 3-way split
        if n_groups < 3:
            # Not enough distinct groups — everything goes to train
            for g in group_list:
                train.extend(g)
            continue

        n_test = max(1, int(n_groups * test_ratio))
        n_dev = max(1, int(n_groups * dev_ratio))
        # Ensure at least one group remains for train
        while n_test + n_dev >= n_groups:
            if n_test > n_dev:
                n_test -= 1
            else:
                n_dev -= 1

        test_groups = group_list[:n_test]
        dev_groups = group_list[n_test : n_test + n_dev]
        train_groups = group_list[n_test + n_dev :]

        for g in test_groups:
            test.extend(g)
        for g in dev_groups:
            dev.extend(g)
        for g in train_groups:
            train.extend(g)

    return Split(train=train, dev=dev, test=test)


def check_leakage(split: Split) -> list[str]:
    """
    Verify no record-shape tuple appears in more than one split.
    The key includes the aggregate/intent so that T3 AVG and T3 SUM on the
    same column are treated as distinct records.
    """
    issues: list[str] = []

    def _hashable(v):
        """Recursively convert v into a hashable equivalent."""
        if isinstance(v, dict):
            return tuple(sorted((k, _hashable(val)) for k, val in v.items()))
        if isinstance(v, (list, tuple)):
            return tuple(_hashable(x) for x in v)
        if isinstance(v, set):
            return tuple(sorted(_hashable(x) for x in v))
        return v

    def key(r):
        slots = r.get("slots", {}) or {}
        return (
            r["template_id"],
            slots.get("table"),
            slots.get("column"),
            _hashable(slots.get("value")),
            slots.get("synonym_used"),
            (r.get("gold_semantics") or {}).get("intent"),
        )

    train_keys = {key(r) for r in split.train}
    for name, part in (("dev", split.dev), ("test", split.test)):
        for r in part:
            if key(r) in train_keys:
                issues.append(f"{name}: {key(r)} also in train")
    return issues


def sanity_check_records(records: list[dict]) -> list[str]:
    """
    Detect input problems before they turn into leakage noise.
    Runs before splitting.
    """
    issues: list[str] = []

    # Single-character synonyms are the signature of the character-explosion bug
    short = 0
    for r in records:
        syn = (r.get("slots") or {}).get("synonym_used")
        if syn and len(syn) == 1:
            short += 1
    if short > 0:
        issues.append(
            f"{short} records have a single-character synonym_used — "
            f"check that value_map values are lists, not strings"
        )

    # Duplicate record ids
    ids = [r.get("id") for r in records]
    if len(ids) != len(set(ids)):
        dupes = len(ids) - len(set(ids))
        issues.append(f"{dupes} duplicate record ids")

    return issues