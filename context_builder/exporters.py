"""Write context.json, context.review.json, terminology_map.tsv."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_context(out_dir: Path, context: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_review(out_dir: Path, context: dict[str, Any], threshold: float = 0.8) -> None:
    """Same content, plus a `needs_review` flag wherever confidence < threshold."""
    review = json.loads(json.dumps(context))  # deep copy
    for tkey, tentry in review["tables"].items():
        _flag(tentry, threshold)
        for ckey, centry in tentry.get("columns", {}).items():
            _flag(centry, threshold)
    (out_dir / "context.review.json").write_text(
        json.dumps(review, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _flag(entry: dict[str, Any], threshold: float) -> None:
    conf = entry.get("confidence", {})
    entry["needs_review"] = {
        field: c for field, c in conf.items() if c < threshold
    }


def write_terminology_tsv(out_dir: Path, context: dict[str, Any]) -> None:
    path = out_dir / "terminology_map.tsv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["scope", "kind", "name", "term", "mapped_to", "source"])
        for tkey, tentry in context["tables"].items():
            for syn in tentry.get("synonyms", []):
                w.writerow(["table", "synonym", tkey, syn, tkey,
                            tentry["provenance"].get("synonyms", "")])
            for ckey, centry in tentry.get("columns", {}).items():
                for syn in centry.get("synonyms", []):
                    w.writerow(["column", "synonym", ckey, syn, ckey,
                                centry["provenance"].get("synonyms", "")])
                for raw, aliases in centry.get("value_map", {}).items():
                    for alias in aliases:
                        w.writerow(["value", "alias", ckey, alias, raw,
                                    centry["provenance"].get("value_map", "")])
        for mkey, mentry in context.get("metrics", {}).items():
            for syn in mentry.get("synonyms", []):
                w.writerow(["metric", "synonym", mkey, syn, mkey, "rule"])
        for fkey, fentry in context.get("filters", {}).items():
            for syn in fentry.get("synonyms", []):
                w.writerow(["filter", "synonym", fkey, syn, fkey, "rule"])