"""Write JSONL + manifest for the generated dataset."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .splitter import Split


def write_split(out_dir: Path, split: Split) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "nl2sql_train.jsonl", split.train)
    _write_jsonl(out_dir / "nl2sql_dev.jsonl", split.dev)
    _write_jsonl(out_dir / "nl2sql_test.jsonl", split.test)


def write_manifest(
    out_dir: Path,
    records: list[dict],
    split: Split,
    realizer_model: str,
    seed: int,
    tier: str = "all",
) -> None:
    by_template = Counter(r["template_id"] for r in records)
    by_difficulty = Counter(r["difficulty"] for r in records)
    ambiguity_records = [
        r for r in records if r["template_id"] == "T16_ambiguity_stress"
    ]

    manifest = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "realizer_model": realizer_model,
        "seed": seed,
        "requested_tier": tier,
        "total_records": len(records),
        "by_template": dict(by_template),
        "by_difficulty": dict(by_difficulty),
        "ambiguity_breakdown": {
            "total": len(ambiguity_records),
            "terms": sorted(
                {
                    r.get("slots", {}).get("column")
                    for r in ambiguity_records
                    if r.get("slots", {}).get("column")
                }
            ),
        },
        "split_sizes": {
            "train": len(split.train),
            "dev": len(split.dev),
            "test": len(split.test),
        },
        # Derive from what actually ran, not what was requested
        "tiers_included": sorted(by_difficulty.keys()),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=list),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=list) + "\n")