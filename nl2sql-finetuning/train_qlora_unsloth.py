"""
QLoRA fine-tuning for company-specific NL2SQL with Unsloth.

Input:
  data/context.json
  data/nl2sql_train_llm_refined.jsonl
  data/nl2sql_dev.jsonl

Only the training split is optimized on. Dev is used for evaluation.
The test split is intentionally NOT loaded by this script.
"""

import os
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List

import torch
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    if not rows:
        raise ValueError(f"No records found in {path}")
    return rows


def compact_schema(context: Dict[str, Any], record: Dict[str, Any]) -> str:
    """Include only tables mentioned by this example, with available column descriptions."""
    tables = context.get("tables", {})
    requested = record.get("entities_used") or []
    # Normalize entity names: records generally use public.table_name.
    selected = []
    for entity in requested:
        key = entity if entity in tables else f"public.{str(entity).split('.')[-1]}"
        if key in tables and key not in selected:
            selected.append(key)

    # Fallback: infer referenced table names from SQL when entity metadata is missing.
    if not selected:
        sql = record.get("sql", "")
        import re
        names = set(re.findall(r"\b(?:FROM|JOIN)\s+(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)", sql, re.I))
        for name in sorted(names):
            key = f"public.{name}"
            if key in tables and key not in selected:
                selected.append(key)

    lines = []
    for table_key in selected:
        table = tables[table_key]
        lines.append(f"TABLE {table_key}")
        purpose = table.get("purpose")
        if purpose:
            lines.append(f"  Purpose: {purpose}")
        columns = table.get("columns", {})
        for col_key, col_info in columns.items():
            col_name = str(col_key).split(".")[-1]
            col_purpose = col_info.get("purpose", "") if isinstance(col_info, dict) else ""
            dtype = col_info.get("data_type") if isinstance(col_info, dict) else None
            desc = f" — {col_purpose}" if col_purpose else ""
            type_desc = f" ({dtype})" if dtype else ""
            lines.append(f"  - {col_name}{type_desc}{desc}")

    if not lines:
        lines.append("Relevant schema metadata was not available for this record.")
    return "\n".join(lines)


def business_context(context: Dict[str, Any], record: Dict[str, Any]) -> str:
    # Avoid putting the entire large context file in every prompt. Select entries
    # whose key/synonyms/rule text overlap this example's question or gold SQL.
    import re
    question_sql = (str(record.get("question", "")) + " " +
                    str(record.get("sql", ""))).lower()
    tokens = set(re.findall(r"[a-z_]+", question_sql))

    def relevant_entries(section: str) -> Dict[str, Any]:
        result = {}
        for key, value in context.get(section, {}).items():
            haystack = key.lower() + " " + json.dumps(value, ensure_ascii=False).lower()
            words = set(re.findall(r"[a-z_]+", haystack))
            if key.lower() in question_sql or len(tokens & words) >= 2:
                result[key] = value
        return result

    selected_tables = {str(x) for x in (record.get("entities_used") or [])}
    selected_tables |= {f"public.{x.split('.')[-1]}" for x in list(selected_tables)}
    forbidden = []
    for item in context.get("forbidden", []):
        applies = set(item.get("applies_to", []))
        if not applies or any(any(table in col for table in selected_tables) for col in applies):
            forbidden.append(item)

    obj = {"domain": context.get("domain", ""),
           "metrics": relevant_entries("metrics"),
           "filters": relevant_entries("filters"),
           "ambiguities": relevant_entries("ambiguities"),
           "forbidden": forbidden}
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_text(record: Dict[str, Any], context: Dict[str, Any], tokenizer) -> str:
    schema = compact_schema(context, record)
    domain_context = business_context(context, record)
    question = str(record["question"]).strip()
    sql = str(record["sql"]).strip()
    system = (
        "You are a company-specific NL2SQL assistant. Generate one PostgreSQL query "
        "that answers the user's question using only the supplied schema and business context. "
        "Return SQL only, with no Markdown fences or explanation. Do not invent tables or columns."
    )
    user = (
        f"DOMAIN AND BUSINESS CONTEXT:\n{domain_context}\n\n"
        f"RELEVANT DATABASE SCHEMA:\n{schema}\n\n"
        f"QUESTION:\n{question}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": sql},
    ]
    # Use the selected model's own chat template.
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
    except Exception as exc:
        raise RuntimeError(
            "The chosen tokenizer has no usable chat template. Select an Instruct/chat "
            "checkpoint supported by Unsloth, or add a model-specific template."
        ) from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv(
        "MODEL_NAME", "unsloth/Qwen2.5-Coder-3B-Instruct"
    ), help="Any compatible Unsloth Hugging Face model ID")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="outputs/nl2sql-qlora")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--save-merged-16bit", action="store_true",
                        help="Also export merged 16-bit model (needs much more RAM/VRAM)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    context_path = data_dir / "context.json"
    train_path = data_dir / "nl2sql_train_llm_refined.jsonl"
    dev_path = data_dir / "nl2sql_dev.jsonl"
    for p in (context_path, train_path, dev_path):
        if not p.exists():
            raise FileNotFoundError(
                f"Missing {p}. See README_QLORA_UNSLOTH.md for the required layout."
            )

    context = json.loads(context_path.read_text(encoding="utf-8"))
    train_rows = read_jsonl(train_path)
    dev_rows = read_jsonl(dev_path)

    # Basic guardrails against accidental split misuse or leakage.
    train_ids = {str(r.get("id")) for r in train_rows}
    dev_ids = {str(r.get("id")) for r in dev_rows}
    overlap = train_ids & dev_ids
    if overlap:
        raise ValueError(f"Train/dev ID overlap detected ({len(overlap)} records).")
    for split_name, rows in (("train", train_rows), ("dev", dev_rows)):
        for i, row in enumerate(rows):
            if not row.get("question") or not row.get("sql"):
                raise ValueError(f"{split_name} row {i} lacks question/sql.")

    print(f"Model: {args.model}")
    print(f"Train rows: {len(train_rows)} | Dev rows: {len(dev_rows)}")
    print("Test split is not loaded or used.")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        dtype=None,  # auto-select bf16/fp16
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
        use_rslora=False,
        loftq_config=None,
    )

    train_texts = [build_text(r, context, tokenizer) for r in train_rows]
    dev_texts = [build_text(r, context, tokenizer) for r in dev_rows]
    train_ds = Dataset.from_dict({"text": train_texts})
    dev_ds = Dataset.from_dict({"text": dev_texts})

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use a conservative config compatible with recent TRL releases.
    training_args = SFTConfig(
        output_dir=str(output_dir),
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        weight_decay=0.01,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        optim="adamw_8bit",
        seed=3407,
        report_to="none",
        packing=False,
        dataset_num_proc=2,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=dev_ds,
        args=training_args,
    )
    trainer.train()

    # Save the LoRA adapter and tokenizer. This is the primary training artifact.
    adapter_dir = output_dir / "final_adapter"
    trainer.model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"\nSaved LoRA adapter to: {adapter_dir.resolve()}")

    # Record reproducibility details.
    metadata = {
        "base_model": args.model,
        "train_file": str(train_path),
        "dev_file": str(dev_path),
        "train_rows": len(train_rows),
        "dev_rows": len(dev_rows),
        "test_used_during_training": False,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "max_seq_length": args.max_seq_length,
        "lora_r": 16,
        "quantization": "4-bit QLoRA",
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    if args.save_merged_16bit:
        merged_dir = output_dir / "merged_16bit"
        trainer.model.save_pretrained_merged(
            str(merged_dir), tokenizer, save_method="merged_16bit"
        )
        print(f"Saved merged model to: {merged_dir.resolve()}")

    print("Training complete. Evaluate on the held-out test split only after decisions")
    print("and hyperparameters are frozen; do not use test results to tune this run.")


if __name__ == "__main__":
    main()
