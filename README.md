# Enterprise Natural Language-to-SQL (NL2SQL) Platform

A PostgreSQL-focused Natural Language-to-SQL platform that converts business questions into SQL, validates the generated statement, executes it through a read-only database connection, and presents the results through interactive web interfaces.

The project is organized into two complementary pipelines, plus an optional fine-tuning bridge between them:

- **Pipeline 1 – Schema, Business Context and Dataset Preparation:** extracts database metadata, builds business-aware context, and generates verified NL–SQL training/evaluation datasets.
- **Pipeline 1.5 – QLoRA Fine-Tuning:** consumes Pipeline 1's dataset artifacts and produces a domain-adapted LoRA adapter that Pipeline 2 can serve via Ollama. This stage is not required for Pipeline 2 to run; it is an accuracy improvement path.
- **Pipeline 2 – NL2SQL Application and Query Execution:** accepts natural-language questions, invokes a configured language model, validates SQL, executes approved queries against PostgreSQL, and displays the returned data.

> **Implementation note:** This README documents the repository behavior described in the supplied project context. It deliberately distinguishes implemented behavior from known configuration mismatches and limitations. Review the [Known limitations and configuration checks](#15-known-limitations-and-configuration-checks) section before using the application with a real database.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
  - [1.1 Objectives](#11-objectives)
  - [1.2 High-Level Architecture](#12-high-level-architecture)
  - [1.3 Pipeline Responsibilities](#13-pipeline-responsibilities)
- [2. Technology Stack](#2-technology-stack)
- [3. Repository Organization](#3-repository-organization)
  - [3.1 Pipeline 1 – Schema Extractor and Dataset Generator](#31-pipeline-1--schema-extractor-and-dataset-generator)
  - [3.2 Pipeline 2 – Application](#32-pipeline-2--application)
  - [3.3 Pipeline 1.5 – Fine-Tuning Workspace](#33-pipeline-15--fine-tuning-workspace)
- [4. Pipeline 1 – Schema, Context and Dataset Preparation](#4-pipeline-1--schema-context-and-dataset-preparation)
  - [4.1 Pipeline 1 Workflow](#41-pipeline-1-workflow)
  - [4.2 Prerequisites](#42-prerequisites)
  - [4.3 Environment Setup](#43-environment-setup)
  - [4.4 Step 1: Extract Database Schema](#44-step-1-extract-database-schema)
  - [4.5 Step 2: Define Business Rules](#45-step-2-define-business-rules)
  - [4.6 Step 3: Build Business Context](#46-step-3-build-business-context)
  - [4.7 Step 4: Generate NL–SQL Dataset](#47-step-4-generate-nlsql-dataset)
  - [4.8 Step 5: Review and Validate Outputs](#48-step-5-review-and-validate-outputs)
  - [4.9 Dataset Record Structure](#49-dataset-record-structure)
  - [4.10 Pipeline 1 CLI Reference](#410-pipeline-1-cli-reference)
- [5. Pipeline 1.5 – QLoRA Fine-Tuning (Bridge Between Pipelines 1 and 2)](#5-pipeline-15--qlora-fine-tuning-bridge-between-pipelines-1-and-2)
  - [5.1 Position in the Overall Architecture](#51-position-in-the-overall-architecture)
  - [5.2 Input Artifact Contract](#52-input-artifact-contract)
  - [5.3 Prompt Construction](#53-prompt-construction)
  - [5.4 Training Procedure](#54-training-procedure)
  - [5.5 Optional Continued Training (Second Epoch)](#55-continued-training-second-epoch)
  - [5.6 GGUF Export and Ollama Registration](#56-gguf-export-and-ollama-registration)
  - [5.7 Relationship to Pipeline 2](#57-relationship-to-pipeline-2)
  - [5.8 Fine-Tuning-Specific Limitations](#58-fine-tuning-specific-limitations)
- [6. Pipeline 2 – NL2SQL Application](#6-pipeline-2--nl2sql-application)
  - [6.1 Pipeline 2 Architecture](#61-pipeline-2-architecture)
  - [6.2 Query Lifecycle](#62-query-lifecycle)
  - [6.3 Backend Components](#63-backend-components)
  - [6.4 SQL Validation and Read-Only Execution](#64-sql-validation-and-read-only-execution)
  - [6.5 Supported LLM Providers](#65-supported-llm-providers)
  - [6.6 Frontend Applications](#66-frontend-applications)
- [7. Pipeline 2 – Installation and Configuration](#7-pipeline-2--installation-and-configuration)
  - [7.1 Prerequisites](#71-prerequisites)
  - [7.2 Configure Environment Variables](#72-configure-environment-variables)
  - [7.3 PostgreSQL Configuration](#73-postgresql-configuration)
  - [7.4 Ollama Configuration](#74-ollama-configuration)
  - [7.5 Cloud Provider Configuration](#75-cloud-provider-configuration)
- [8. Running Pipeline 2 Locally](#8-running-pipeline-2-locally)
  - [8.1 Start the Backend](#81-start-the-backend)
  - [8.2 Start the React Frontend](#82-start-the-react-frontend)
  - [8.3 Verify the Installation](#84-verify-the-installation)
- [9. Running Pipeline 2 with Docker Compose](#9-running-pipeline-2-with-docker-compose)
  - [9.1 Build and Start Services](#91-build-and-start-services)
  - [9.2 View Logs and Service Status](#92-view-logs-and-service-status)
  - [9.3 Start All Frontends](#93-start-all-frontends)
  - [9.4 Stop and Restart Services](#94-stop-and-restart-services)
  - [9.5 Container Networking](#95-container-networking)
- [10. REST API Reference](#10-rest-api-reference)
  - [10.1 Health Check](#101-health-check)
  - [10.2 Query Endpoint](#102-query-endpoint)
  - [10.3 Schema Endpoint](#103-schema-endpoint)
  - [10.4 Cache and Administration Endpoints](#104-cache-and-administration-endpoints)
- [11. Caching, Logging and Monitoring](#11-caching-logging-and-monitoring)
- [12. End-to-End Usage Example](#12-end-to-end-usage-example)
- [13. Troubleshooting](#13-troubleshooting)
- [14. Security and Operational Recommendations](#14-security-and-operational-recommendations)
- [15. Known Limitations and Configuration Checks](#15-known-limitations-and-configuration-checks)
- [16. Development Guidelines](#16-development-guidelines)
- [17. Outputs and Deliverables](#17-outputs-and-deliverables)
- [18. Future Improvements](#18-future-improvements)

---

# 1. Project Overview

## 1.1 Objectives

The platform is intended to make structured business data accessible through natural-language questions without requiring every user to write SQL manually.

Its principal objectives are:

1. **Natural-language access:** allow users to ask questions in ordinary business language.
2. **Schema awareness:** provide the language model with database structure and relevant metadata.
3. **Business-rule awareness:** represent business terminology, metric definitions, filters and operational constraints.
4. **Controlled SQL generation:** validate model-generated SQL before database execution.
5. **Read-only data access:** execute accepted queries inside a read-only PostgreSQL transaction.
6. **Interactive results:** present generated SQL, tabular records and visualizations.
7. **Operational traceability:** associate requests with correlation IDs and structured logs.
8. **Reusable data preparation:** generate schema context and NL–SQL datasets that can support model training, evaluation and prompt development.

## 1.2 High-Level Architecture

```text
                         PIPELINE 1
              SCHEMA, CONTEXT & DATASET PREPARATION

       PostgreSQL Database / Existing Database Metadata
                            |
                            v
                    Schema Extraction
                      extract_schema.py
                            |
                            v
                        schema.json
                            |
                            +----------------------+
                            |                      |
                            v                      v
                  business_rules.yaml       Schema Metadata
                            |                      |
                            +----------+-----------+
                                       |
                                       v
                              Context Builder
                         Validation + Enrichment
                                       |
                                       v
                                  context.json
                           /          |          \
                          v           v           v
                   Review JSON   Terminology   Dataset
                                  Mapping       Generator
                                                   |
                                                   v
                                      Train / Dev / Test JSONL
                                      + Dataset Manifest


                  PIPELINE 1.5  (FINE-TUNING)
          context.json + nl2sql_train_llm_refined.jsonl + nl2sql_dev.jsonl
                            |
                            v
                     train_qlora_unsloth.py
                (Unsloth + TRL SFTTrainer, 4-bit QLoRA)
                            |
                            v
                  final_adapter/ (LoRA weights)
                            |
                            +--> GGUF export (q4_k_m)
                                       |
                                       v
                              ollama create / serve


                         PIPELINE 2
                    NL2SQL APPLICATION RUNTIME

             User enters a natural-language question
                            |
                            v
                          React 
                            |
                            v
                       FastAPI Backend
                            |
                            v
                   Provider-specific LLM
             (Ollama / Cloud / fine-tuned model)
                            |
                            v
                    SQL Response Parsing
                            |
                            v
                     SQL Validation
                 Regex + SQLGlot AST Checks
                            |
                     +------+------+
                     |             |
                  Rejected       Accepted
                     |             |
                     v             v
                  API Error   SQL Executor
                                   |
                                   v
                           asyncpg Connection Pool
                                   |
                                   v
                         Read-only PostgreSQL
                                   |
                                   v
                          Rows + SQL + Metadata
                                   |
                                   v
                       Frontend Table / Charts
```

Pipeline 1 prepares structured database and business knowledge. Pipeline 1.5 adapts a language model to that knowledge. Pipeline 2 is the interactive application that uses its configured schema/rule context and an LLM to answer user questions.

The pipelines are complementary but not currently wired together as a fully automated deployment process. Pipeline 1 exports JSON/JSONL artifacts; Pipeline 2's checked-in schema and rule loaders currently expect SQL DDL and YAML files at different paths. Pipeline 1.5 consumes Pipeline 1 outputs under slightly different filenames than Pipeline 1 emits by default. See [Known limitations and configuration checks](#15-known-limitations-and-configuration-checks) and [Fine-Tuning-Specific Limitations](#58-fine-tuning-specific-limitations).

## 1.3 Pipeline Responsibilities

| Area | Pipeline 1 | Pipeline 2 |
|---|---|---|
| Primary purpose | Prepare schema/context and NL–SQL datasets | Serve interactive NL2SQL queries |
| Main inputs | Database URL, schema, business rules | Environment settings, PostgreSQL, model provider |
| Main processing | Extraction, validation, enrichment, templating, verification and splitting | Prompt construction, model generation, SQL validation and execution |
| Main outputs | `schema.json`, context files, JSONL datasets, manifest | SQL, query results, row count and correlation ID |
| Main technologies | SQLAlchemy, SQLGlot, Pydantic, YAML, LLM | FastAPI, Ollama/cloud SDKs, SQLGlot, asyncpg, React |
| Execution style | Offline/preparation workflow | Request/response application |

> The fine-tuning stage (Section 5) is not shown in this table; see [5.7 Relationship to Pipeline 2](#57-relationship-to-pipeline-2) for how it plugs in.

---

# 2. Technology Stack

| Layer | Technologies |
|---|---|
| Database | PostgreSQL |
| Schema extraction | Python, SQLAlchemy, pandas |
| Context definition | YAML, JSON, Pydantic |
| SQL parsing and validation | SQLGlot |
| Context enrichment | Ollama or supported API-based LLM adapters |
| Dataset generation | Python template/binding system, LLM realization |
| Fine-tuning | Unsloth, TRL (`SFTTrainer`/`SFTConfig`), PEFT (LoRA), bitsandbytes (4-bit), `datasets` |
| Model export | Unsloth GGUF export (`llama.cpp` converter), Ollama (`ollama create`) |
| Backend API | FastAPI, Uvicorn, Pydantic |
| Local model serving | Ollama |
| Cloud model integrations | OpenAI-compatible API, Google GenAI, Anthropic |
| Database access | asyncpg connection pool |
| Frontend | React, TypeScript, Vite |
| Deployment | Docker, Docker Compose, Nginx |
| Logging | Structured JSON logging with correlation IDs |

---

# 3. Repository Organization

The project context describes three working areas: the schema/dataset preparation workspace, the fine-tuning workspace, and the application workspace. If they are maintained as separate repositories or folders, preserve that separation when following the commands below.

## 3.1 Pipeline 1 – Schema Extractor and Dataset Generator

```text
schema-extractor/
│
├── extract_schema.py
├── business_rules.yaml
├── requirements.txt
├── database_urls.txt
├── schema.json
│
├── context_builder/
│   ├── __init__.py
│   ├── main.py
│   ├── loader.py
│   ├── validator.py
│   ├── enricher.py
│   ├── merger.py
│   ├── exporters.py
│   └── prompts/
│       ├── table_purpose.txt
│       └── column_purpose.txt
│
├── dataset_generator/
│   ├── __init__.py
│   ├── main.py
│   ├── binder.py
│   ├── templates.py
│   ├── templates_medium.py
│   ├── templates_hard.py
│   ├── join_graph.py
│   ├── metric_builder.py
│   ├── filter_builder.py
│   ├── cte_builder.py
│   ├── window_builder.py
│   ├── ambiguity_binder.py
│   ├── sql_builder.py
│   ├── realizer.py
│   ├── verifier.py
│   ├── roundtrip.py
│   ├── splitter.py
│   ├── exporter.py
│   └── prompts/
│       └── realize_question.txt
│
├── out/
├── out_smoke/
├── out_smoke2/
└── out-backup/
```

The output directories shown above are generated artifacts and historical run directories, not source modules.

## 3.2 Pipeline 2 – Application

```text
enterprise-text-to-sql (root)/
│
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── api/
│   │   ├── routes/
│   │   │   ├── query.py
│   │   │   ├── health.py
│   │   │   ├── schema.py
│   │   │   └── admin.py
│   │   ├── schemas/
│   │   └── middleware/
│   ├── core/
│   │   ├── llm/
│   │   ├── schema/
│   │   ├── rules/
│   │   └── config.py
│   ├── execution/
│   │   ├── connection_pool.py
│   │   └── executor.py
│   ├── validation/
│   │   └── validator.py
│   └── monitoring/
│       ├── structured_logging.py
│       └── logger.py
│
├── config/
│   ├── schema.json
│   ├── business_rules.json
│   └── security/
│       └── forbidden_patterns.yaml
│
├── frontend-react/
├── docker-compose.yaml
├── .env
└── APPLICATION_CONTEXT.md
```

Some configuration files expected by the current loaders are not represented in this checked-in layout. The exact expected paths are described later in this README.

## 3.3 Pipeline 1.5 – Fine-Tuning Workspace

```text
nl2sql-finetuning/
│
├── train_qlora_unsloth.py
├── fine_tuning.ipynb
├── README_QLORA_UNSLOTH.md
│
├── data/
│   ├── context.json
│   ├── nl2sql_train_llm_refined.jsonl
│   ├── nl2sql_dev.jsonl
│   └── nl2sql_test.jsonl
│
└── outputs/
    ├── nl2sql-qlora/
    │   ├── run_metadata.json
    │   ├── final_adapter/
    │   └── checkpoint-*/
    └── gguf-epoch2/
        └── <Model>.Q4_K_M.gguf
```

`data/` and `outputs/` are generated or copied artifacts, not checked-in source. See [Section 5](#5-pipeline-15--qlora-fine-tuning-bridge-between-pipelines-1-and-2) for training and deployment.

---

# 4. Pipeline 1 – Schema, Context and Dataset Preparation

Pipeline 1 converts a database's technical structure and business definitions into a structured context and a collection of natural-language/SQL examples.

## 4.1 Pipeline 1 Workflow

```text
Database
   |
   v
[1] Schema Extraction
   |
   |-- Tables and views
   |-- Columns and data types
   |-- Primary and foreign keys
   |-- Indexes and comments
   |-- Row/column profiles
   |
   v
schema.json
   |
   +-----------------------------+
   |                             |
   v                             v
business_rules.yaml        Schema Index
   |                             |
   +--------------+--------------+
                  |
                  v
         [2] Context Builder
                  |
          Rule Validation
                  |
          Optional LLM Enrichment
                  |
          Rule/LLM Merge
                  |
                  v
       context.json / review.json
       terminology_map.tsv
                  |
                  v
       [3] Dataset Generator
                  |
          Template Registry
                  |
          Binding Enumeration
                  |
          SQL Construction
                  |
          AST Verification
                  |
          NL Question Realization
                  |
          Optional Round-trip Check
                  |
          Optional DB Execution
                  |
          Group-aware Data Splitting
                  |
                  v
        train.jsonl / dev.jsonl / test.jsonl
                + manifest.json
```

## 4.2 Prerequisites

Install the following before running Pipeline 1:

- Python 3.10 or a compatible Python version supported by the installed dependencies.
- Access to the PostgreSQL database being inspected.
- A database account with sufficient privileges to inspect metadata and read sampled rows.
- The Python packages listed in `requirements.txt`.
- Optional: Ollama or an API-compatible LLM provider for context enrichment and question realization.
- Optional: a read-only database URL for dataset execution verification.

The precise dependency versions are governed by the workspace's `requirements.txt`.

## 4.3 Environment Setup

Open a terminal in the Pipeline 1 workspace:

```bash
cd schema-extractor
```

Create and activate a virtual environment.

**Windows PowerShell**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Configure the database connection through the environment or the project's connection URL input mechanism. Do not commit credentials or publish connection strings.

For commands that accept `--url`, a SQLAlchemy-compatible PostgreSQL URL can be supplied directly:

```text
postgresql+psycopg2://<username>:<password>@<host>:<port>/<database>
```

Use the driver scheme supported by the installed SQLAlchemy PostgreSQL driver.

## 4.4 Step 1: Extract Database Schema

### Purpose

`extract_schema.py` introspects the target database and serializes its structure and selected data profiles into a JSON document.

The extractor uses SQLAlchemy inspection and database queries to identify:

- Database and schema metadata.
- Tables and views.
- Column names, types, nullability and defaults.
- Primary-key information.
- Foreign-key relationships.
- Index names, indexed columns and uniqueness.
- Table comments where available.
- Table row counts and column profiles.
- Sample values for selected columns.
- Approximate table storage size where supported.

### Execute schema extraction

From the Pipeline 1 root:

```bash
python extract_schema.py --url "<DATABASE_URL>" --out schema.json
```

To control the number of rows sampled per table:

```bash
python extract_schema.py \
  --url "<DATABASE_URL>" \
  --out schema.json \
  --sample-rows 1000
```

To restrict extraction to selected schemas:

```bash
python extract_schema.py \
  --url "<DATABASE_URL>" \
  --out schema.json \
  --schemas public
```

Multiple schema names may be supplied according to the CLI's list argument.

If `--url` is omitted, the extractor uses `DATABASE_URL` from the environment.

### Output

```text
schema.json
```

The generated JSON is the primary structural input to the context builder and dataset generator.

### Important profiling behavior

Some profile information is sample-based, while other values are obtained directly from the database. For example, the total table row count is database-derived, while sample values and several column statistics are based on the sampled DataFrame. Sampling does not specify a deterministic row order, so the particular sample may vary between runs.

## 4.5 Step 2: Define Business Rules

### Purpose

Database metadata explains how data is stored. Business rules explain what that data means to the organization.

`business_rules.yaml` provides the business vocabulary and constraints consumed by the context builder.

The supported rule model includes:

| Rule category | Purpose |
|---|---|
| Entities | Defines business entities/tables, their purpose, synonyms and relationships |
| Columns | Defines column purpose, synonyms, value mappings and notes |
| Metrics | Defines reusable business calculations and their SQL expressions |
| Filters | Defines reusable SQL conditions and their natural-language aliases |
| Forbidden rules | Describes operations or interpretations that generated examples should avoid |
| Ambiguities | Defines terms that can refer to multiple columns and how to resolve them |

The top-level business-rule structure supports:

- `version`
- `domain`
- `entities`
- `metrics`
- `filters`
- `forbidden`
- `ambiguities`

### Example structure

The following is an illustrative structural example, not a replacement for the project's actual business-rule definitions:

```yaml
version: "1.0"
domain: "business_domain"

entities:
  orders:
    purpose: "Represents customer orders"
    synonyms:
      - "purchases"
      - "sales orders"
    columns:
      order_status:
        purpose: "Current status of an order"
        synonyms:
          - "order state"

metrics:
  total_orders:
    sql: "COUNT(*)"
    from: "public.orders"
    synonyms:
      - "number of orders"

filters:
  completed_orders:
    sql: "order_status = 'completed'"
    synonyms:
      - "completed purchases"

forbidden: []

ambiguities: {}
```

Use the actual schema's table and column names. The context builder validates references against the extracted schema; invalid or unresolved references should be corrected before proceeding.

### Business-rule design recommendations

1. Prefer explicit, human-reviewed metric definitions.
2. Use synonyms that reflect how business users phrase questions.
3. Define value aliases for codes and categorical values where necessary.
4. Document ambiguous terms rather than relying on the model to guess.
5. Keep reusable filters consistent with the database's actual values.
6. Do not introduce columns or relationships that are absent from the schema.

## 4.6 Step 3: Build Business Context

### Purpose

The context builder combines the extracted schema with the authored business rules and optionally enriches table/column descriptions through an LLM.

Its major stages are:

1. Load schema JSON and business-rule YAML.
2. Construct a fully qualified schema index.
3. Validate entity/column references, rule references, synonyms and SQL fragments.
4. Optionally enrich table and column purposes/synonyms with an LLM.
5. Merge authored and generated information.
6. Attach provenance and confidence metadata.
7. Export the context, review document and terminology map.

### Run with LLM enrichment

```bash
python -m context_builder.main \
  --schema schema.json \
  --rules business_rules.yaml \
  --out out
```

Configure the provider before execution using the environment variables described below.

### Run without LLM enrichment

```bash
python -m context_builder.main \
  --schema schema.json \
  --rules business_rules.yaml \
  --out out \
  --no-llm
```

The `--no-llm` option uses the authored rules without requesting model-generated enrichment. This is useful for deterministic runs and environments without an LLM endpoint.

### Context-builder environment variables

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | Enrichment provider: `openai`, `anthropic` or `ollama` |
| `LLM_MODEL` | Optional model override |
| `GROQ_API_KEY` | API key used by the OpenAI-compatible/Groq adapter |
| `OLLAMA_URL` | Optional Ollama endpoint override |

The context builder loads `.env` through `load_dotenv()`.

### Generated outputs

```text
out/
├── context.json
├── context.review.json
└── terminology_map.tsv
```

**`context.json`**

The primary context artifact. It contains domain metadata, enriched table/column meanings, synonyms, metrics, filters, forbidden rules, ambiguity definitions and associated metadata.

**`context.review.json`**

A review-oriented version of the context containing flags for lower-confidence fields. The current review threshold is `0.8`.

**`terminology_map.tsv`**

A tab-separated lookup of business synonyms and value aliases mapped to canonical database objects or business definitions.

### Provenance and confidence

The merger prefers authored rule values when both authored and LLM-enriched values exist. Rule-derived values receive confidence `1.0`; LLM-derived values receive confidence `0.6` in the current implementation. Low-confidence fields are surfaced in the review output.

Review `context.review.json` before using the generated context as a source of truth.

## 4.7 Step 4: Generate NL–SQL Dataset

### Purpose

The dataset generator creates question/SQL pairs using a template-and-binding approach.

A **template** describes a reusable SQL query pattern. A **binding** fills the template with concrete tables, columns, values, metrics or relationships from the schema and context.

This approach creates structured examples from the available schema rather than asking an LLM to invent arbitrary SQL from scratch.

### Run the complete generator

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out
```

### Generate without an LLM

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --no-llm
```

With `--no-llm`, question wording is generated using deterministic fallback patterns. LLM-based round-trip synthesis is also unavailable in this mode.

### Generate selected difficulty tiers

Easy:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --tier easy
```

Medium:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --tier medium
```

Hard:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --tier hard
```

All tiers:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --tier all
```

### Template families

The generator currently describes the following template families.

| Tier | Template ID | Pattern |
|---|---|---|
| Easy | T1 | Filter rows by a category/value |
| Easy | T2 | Count rows by category |
| Easy | T3 | Aggregate a numeric column using AVG, SUM, MIN or MAX |
| Easy | T4 | Count distinct values |
| Medium | T5 | Count records through a one-hop join |
| Medium | T6 | Filtered count over a join |
| Medium | T7 | Group by a category and count |
| Medium | T8 | Query a defined business metric |
| Medium | T9 | Combine a business metric with a filter |
| Hard | T10 | Top-N groups by an aggregate |
| Hard | T11 | Threshold-based grouped query using a CTE |
| Hard | T12 | Anti-join using EXISTS |
| Hard | T13 | Aggregate across a two-hop join |
| Hard | T14 | Metric with a related-table join constraint |
| Hard | T15 | Set operation using UNION |
| Hard | T16 | Resolve a declared ambiguous business term |
| Hard | T17 | Running total using a window expression |

Template availability depends on the schema and context satisfying the template's binding requirements. Not every template will necessarily produce examples for every database.

### Select individual templates

The `--templates` argument can restrict generation to selected template IDs. For example:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --templates T1 T2 T3 T7
```

Unknown template IDs are filtered out when the registry is selected.

### Optional SQL round-trip verification

By default, when an LLM is available, the generator can ask the model to independently synthesize SQL from the realized question and a compact schema listing. The generated SQL is parsed and normalized before comparison with the template SQL.

To skip this check:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --no-roundtrip
```

`--no-roundtrip` does not disable LLM question realization. Use `--no-llm` to disable both LLM-based question realization and round-trip synthesis.

### Optional database execution verification

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --verify-execute \
  --db-url "<READ_ONLY_DATABASE_URL>"
```

This option executes generated SQL against the supplied database and records execution verification information. Use a database account with read-only privileges.

**Important:** the dataset generator does not enforce read-only access on the supplied verification connection in code. The safety of this operation depends on the privileges of the database account and the database environment supplied.

### Reproducible splitting

The generator supports a random seed:

```bash
python -m dataset_generator.main \
  --schema schema.json \
  --context out/context.json \
  --out out \
  --seed 42
```

The splitter groups related examples by template/binding-derived keys before assigning groups to train, dev and test partitions. This is intended to reduce structural leakage between partitions.

## 4.8 Step 5: Review and Validate Outputs

After generation, inspect the output directory:

```text
out/
├── context.json
├── context.review.json
├── terminology_map.tsv
├── nl2sql_train.jsonl
├── nl2sql_dev.jsonl
├── nl2sql_test.jsonl
└── dataset_manifest.json
```

The exact record counts depend on schema coverage, business rules, enabled template tiers, verification options and the generator configuration.

Recommended review sequence:

1. Confirm that all expected schema tables and columns are present in `schema.json`.
2. Review `context.review.json` for fields that need human attention.
3. Check that business metrics and filters in `context.json` match their intended definitions.
4. Inspect a sample of questions in each JSONL split.
5. Confirm that each question is paired with the intended SQL.
6. Inspect AST verification and optional round-trip/execution results.
7. Review the dataset manifest for counts and generation metadata.
8. Investigate leakage warnings and suspicious duplicate or short-synonym records.

The leakage checker reports structural overlaps; it does not automatically remove records or abort export.

## 4.9 Dataset Record Structure

Each generated record includes fields such as:

| Field | Description |
|---|---|
| `id` | Unique record identifier |
| `question` | Natural-language question |
| `sql` | Corresponding SQL query |
| `template_id` | Template used to generate the example |
| `difficulty` | Difficulty tier |
| `tags` | Descriptive template tags |
| `split_group_key` | Grouping key used during splitting |
| `slots` | Concrete template bindings |
| `entities_used` | Entities referenced by the example |
| `rules_used` | Business rules used |
| `synonyms_used` | Business terminology used |
| `gold_semantics` | Basic intent, grain and filter semantics |
| `provenance` | Model, prompt hash, template version and seed metadata |
| `verification` | AST, optional round-trip and optional execution information |

The JSONL format stores one JSON record per line and is suitable for downstream training and evaluation workflows.

## 4.10 Pipeline 1 CLI Reference

### Schema extraction

| Argument | Description | Default |
|---|---|---|
| `--url` | SQLAlchemy database URL; falls back to `DATABASE_URL` | Environment |
| `--out` | Output schema JSON path | `schema.json` |
| `--sample-rows` | Maximum rows sampled per table | `1000` |
| `--schemas` | Optional schema-name filter | All eligible non-system schemas |

### Context builder

| Argument | Description | Default |
|---|---|---|
| `--schema` | Input schema JSON | `schema.json` |
| `--rules` | Business-rule YAML | `business_rules.yaml` |
| `--out` | Output directory | `out` |
| `--cache-dir` | Enrichment cache directory | `.cache/context_enricher` |
| `--no-llm` | Disable LLM enrichment | Disabled |

### Dataset generator

| Argument | Description | Default |
|---|---|---|
| `--schema` | Input schema JSON | `schema.json` |
| `--context` | Context JSON | `out/context.json` |
| `--out` | Output directory | `out` |
| `--templates` | Selected template IDs | All selected registry templates |
| `--tier` | `easy`, `medium`, `hard` or `all` | `all` |
| `--no-llm` | Use deterministic question fallback | Disabled |
| `--no-roundtrip` | Skip LLM SQL round-trip check | Disabled |
| `--verify-execute` | Execute generated SQL for verification | Disabled |
| `--db-url` | Database URL for execution verification | Not set |
| `--seed` | Random seed for splitting/provenance | `42` |

---

# 5. Pipeline 1.5 – QLoRA Fine-Tuning (Bridge Between Pipelines 1 and 2)

An stage sits between Pipeline 1 and Pipeline 2. It consumes the JSON/JSONL artifacts produced by the Pipeline 1 dataset generator and produces a fine-tuned LoRA adapter (and a merged GGUF model) that Pipeline 2's Ollama provider can serve as a domain-adapted NL2SQL model.

The workspace is `nl2sql-finetuning/` and is driven by `train_qlora_unsloth.py` plus a Colab notebook (`fine_tuning.ipynb`). Fine-tuning is not required for Pipeline 2 to function; it is an accuracy improvement path for a specific schema and business domain.

## 5.1 Position in the Overall Architecture

```text
                    PIPELINE 1  (preparation)
        schema.json / context.json / nl2sql_*.jsonl
                            |
                            v
                  nl2sql-finetuning/
                  -----------------
                  data/context.json
                  data/nl2sql_train_llm_refined.jsonl
                  data/nl2sql_dev.jsonl
                  data/nl2sql_test.jsonl   (never loaded by trainer)
                            |
                            v
                 train_qlora_unsloth.py
                 (Unsloth + TRL SFTTrainer, 4-bit QLoRA)
                            |
                            v
                 outputs/nl2sql-qlora/final_adapter/
                            |
                            +--> continued training / epoch 2 adapter
                            |
                            +--> GGUF export (q4_k_m)
                                       |
                                       v

		                      `ollama create / ollama serve`
                                       |
                                       v
                    PIPELINE 2  (runtime)
                 OLLAMA_MODEL=<fine-tuned model>
```

## 5.2 Input Artifact Contract

The trainer expects a `data/` directory containing exactly these files. Their names are hard-coded in `train_qlora_unsloth.py`; renaming them in Pipeline 1 requires a corresponding edit to the trainer or a symlink/copy step.

| File | Consumed by | Purpose |
|---|---|---|
| `data/context.json` | `business_context()`, `compact_schema()` | Business context used to build per-example prompts |
| `data/nl2sql_train_llm_refined.jsonl` | Training split | Optimized on |
| `data/nl2sql_dev.jsonl` | Evaluation split | Used for `eval_loss` and best-checkpoint selection |
| `data/nl2sql_test.jsonl` | **Not loaded** | Held out; must not be used for tuning |

Required record fields per JSONL row: `id`, `question`, `sql`. Optional but strongly used: `entities_used`, and any `context.json` structure with top-level `tables`, `domain`, `metrics`, `filters`, `ambiguities`, `forbidden`.

The trainer enforces basic guardrails on load:

1. All three input files must exist; otherwise it raises `FileNotFoundError`.
2. Train/dev `id` sets must be disjoint; overlap raises `ValueError`.
3. Every row must have non-empty `question` and `sql`.

Pipeline 1 must therefore emit a `nl2sql_train_llm_refined.jsonl` file (the LLM-refined variant of `nl2sql_train.jsonl`). If Pipeline 1 only produced `nl2sql_train.jsonl`, copy or regenerate it under the expected name before training. See [15.13 Fine-Tuning Artifact Boundary](#1513-fine-tuning-artifact-boundary).

## 5.3 Prompt Construction

`build_text()` assembles each training example from three pieces:

- **System prompt** — company-specific NL2SQL assistant; PostgreSQL only; schema and business context only; SQL only, no fences or explanation.
- **User prompt** — `DOMAIN AND BUSINESS CONTEXT` (JSON), `RELEVANT DATABASE SCHEMA` (compact text), and `QUESTION`.
- **Assistant turn** — the gold `sql` string.

Two scoping helpers keep prompts small:

- `compact_schema()` includes only tables in `entities_used` (normalized to `public.<name>`), with a regex fallback over `FROM`/`JOIN` in the SQL, and renders table purpose, column type, and column purpose.
- `business_context()` selects only `metrics`, `filters`, `ambiguities`, and `forbidden` entries that overlap the question/SQL tokens or apply to the used tables, instead of embedding the whole `context.json`.

The chat template is taken from the tokenizer via `apply_chat_template`. A tokenizer without a usable chat template raises `RuntimeError` — use an Instruct/chat checkpoint (e.g., the referenced `XGenerationLab/XiYanSQL-QwenCoder-3B-2504`) or add a model-specific template.

## 5.4 Training Procedure

Run from inside `nl2sql-finetuning/`:

```bash
python train_qlora_unsloth.py \
  --model XGenerationLab/XiYanSQL-QwenCoder-3B-2504 \
  --epochs 1
```

The example above overrides the script's default `--epochs 3.0` to run a single epoch; this matches the epoch-1 baseline used by the continued-training flow in 5.5.

The script uses Unsloth `FastLanguageModel` with 4-bit loading and PEFT LoRA (`r=16`, `lora_alpha=16`, `lora_dropout=0.0`, `bias="none"`, Unsloth gradient checkpointing, `random_state=3407`, target modules `q/k/v/o/gate/up/down`). Training is driven by TRL `SFTTrainer`/`SFTConfig` with `packing=False`, cosine schedule, `warmup_ratio=0.05`, `weight_decay=0.01`, `adamw_8bit`, `eval_strategy="epoch"`, `save_strategy="epoch"`, `metric_for_best_model="eval_loss"`, and `report_to="none"`.

Default CLI arguments:

| Argument | Default | Notes |
|---|---|---|
| `--model` | `unsloth/Qwen2.5-Coder-3B-Instruct` (or `MODEL_NAME` env) | Any Unsloth-compatible HF model ID |
| `--data-dir` | `data` | Must contain the four files above |
| `--output-dir` | `outputs/nl2sql-qlora` | Adapter destination |
| `--epochs` | `3.0` | Override per run |
| `--max-seq-length` | `2048` | |
| `--learning-rate` | `2e-4` | |
| `--batch-size` | `2` | |
| `--grad-accum` | `4` | |
| `--save-merged-16bit` | off | High RAM/VRAM cost |

The primary output is `outputs/nl2sql-qlora/final_adapter/` containing the LoRA weights and tokenizer files, and `run_metadata.json` at the output root (i.e., `outputs/nl2sql-qlora/run_metadata.json`). `run_metadata.json` records base model, split file paths, row counts, `test_used_during_training: false`, epochs, LR, max sequence length, LoRA rank, and quantization mode for reproducibility.

## 5.5 Continued Training (Second Epoch)

The Colab notebook demonstrates re-loading the epoch-1 adapter and training a second epoch. This assumes a one-epoch baseline was produced first (see 5.4's example invocation).

1. Read `base_model_name_or_path` from `final_adapter/adapter_config.json`.
2. Load the base with `FastLanguageModel.from_pretrained(..., load_in_4bit=True)`.
3. Attach the existing adapter with `PeftModel.from_pretrained(..., is_trainable=True)`.
4. Rebuild `train_ds`/`dev_ds` via the trainer module's `build_text` and run a fresh `SFTTrainer` with the same config, writing to a new `output-dir`.

Continued training must use a **new** output directory; the notebook asserts the destination does not already exist to avoid overwriting the epoch-1 adapter.

## 5.6 GGUF Export and Ollama Registration

For Pipeline 2 deployment on Ollama:

1. Load the base + adapter with `FastLanguageModel.from_pretrained(model_name=str(ADAPTER_DIR), load_in_4bit=True)`.
2. Call `model.save_pretrained_gguf(export_dir, tokenizer, quantization_method="q4_k_m")`.
3. The converter writes the merged f16 and quantized files to a sibling `*_gguf/` directory (observed: `<Model>.Q4_K_M.gguf`), not the requested `export_dir`. Copy the produced `.gguf` to a stable location.
4. Register it with Ollama and point Pipeline 2 at it:

```bash
ollama create nl2sql-finetuned -f Modelfile   # Modelfile: FROM ./<Model>.Q4_K_M.gguf
ollama serve
```

Then set `OLLAMA_MODEL=nl2sql-finetuned` in Pipeline 2's `.env`. Unsloth may skip writing a Modelfile for models without a known Ollama template mapping (as seen for XiYanSQL); supply one manually.

## 5.7 Relationship to Pipeline 2

- Pipeline 2 works with any configured `OLLAMA_MODEL` or cloud provider.
- A fine-tuned model only improves behavior if Pipeline 2's prompt (schema + business rules + few-shot examples) is consistent with the prompt shape used during training (`DOMAIN AND BUSINESS CONTEXT` + `RELEVANT DATABASE SCHEMA` + `QUESTION` → SQL only). Diverging drastically (e.g., hard-coded few-shot examples for other domains, empty schema due to the known loader path mismatch) will degrade fine-tuned performance.
- Because the trainer builds prompts from Pipeline 1's `context.json` (rich, per-example), while Pipeline 2's current loaders read SQL DDL and YAML at different paths, the cross-pipeline artifact contract is the same open issue flagged in [Known limitations and configuration checks](#15-known-limitations-and-configuration-checks) (see 15.1, 15.2, 15.12).
- The test split (`nl2sql_test.jsonl`) is deliberately excluded from training and validation; evaluate on it only after hyperparameters are frozen.

## 5.8 Fine-Tuning-Specific Limitations

1. **Hard-coded filenames.** `data/nl2sql_train_llm_refined.jsonl` must exist with that exact name; Pipeline 1 emits `nl2sql_train.jsonl` by default. See [15.13](#1513-fine-tuning-artifact-boundary).
2. **GGUF output path.** `save_pretrained_gguf(export_dir, ...)` writes to `<export_dir>_gguf/`, so `list(export_dir.glob("*.gguf"))` returns empty; copy from the `_gguf` sibling.
3. **No Ollama Modelfile generated** for models without a mapping (observed for XiYanSQL); create one manually.
4. **Tokenizer chat template required.** Non-chat checkpoints fail at `build_text()`.
5. **Epoch-2 notebook flow assumes Colab paths** (`/content/...`, Google Drive mount); adapt paths for local or other cloud runs.
6. **No automated evaluation against `nl2sql_test.jsonl`** is included; add a separate evaluation script that checks exact SQL match, execution success, or result equivalence before promoting an adapter.
7. **Trainer does not verify schema/context consistency** with Pipeline 2's runtime loaders; mismatched context is silently accepted at training time.

---

# 6. Pipeline 2 – NL2SQL Application

Pipeline 2 is the interactive application layer. It accepts a question from a frontend, selects a model provider, builds the prompt, obtains SQL, validates the statement, executes it against PostgreSQL and returns structured results.

## 6.1 Pipeline 2 Architecture

```text
                 Frontend
                  React
                  |
                  | POST /api/query
                  v
             FastAPI Router
                  |
                  v
        Request Validation (Pydantic)
                  |
                  v
        Provider Selection / Dispatch
             /             \
            v               v
        Ollama          Cloud LLMs
            \               /
             \             /
              v           v
             SQL Generation
                    |
                    v
             SQL Response Parser
                    |
                    v
               SQLValidator
             /              \
          Reject            Accept
            |                 |
            v                 v
        HTTP Error        SQLExecutor
                              |
                              v
                     asyncpg Connection Pool
                              |
                              v
                  PostgreSQL Read-only Transaction
                              |
                              v
                     Query Result Packaging
                              |
                              v
                 JSON Response + Correlation ID
                              |
                              v
                    Frontend Rendering
```

## 6.2 Query Lifecycle

A typical request follows these steps:

1. The frontend sends a question and optional provider to `POST /api/query`.
2. Pydantic validates the request body.
3. The backend reads or creates a correlation ID.
4. The provider-specific LLM adapter builds the prompt using the configured static context and the current user question.
5. The model returns a SQL response.
6. The response parser extracts the SQL statement.
7. `SQLValidator` applies configured pattern checks and SQLGlot PostgreSQL AST checks.
8. Invalid or unsupported statements are rejected.
9. Accepted SQL is passed to `SQLExecutor`.
10. `DatabaseConnectionPool` executes the statement in a read-only transaction.
11. The backend packages the SQL, result rows, row count and correlation ID.
12. The frontend displays the SQL and data, and may derive visualizations from the returned rows.

## 6.3 Backend Components

| Component | Responsibility |
|---|---|
| `backend/main.py` | FastAPI application, startup/shutdown lifecycle, CORS and router registration |
| `api/routes/query.py` | Query generation, validation, execution and cache routes |
| `api/routes/health.py` | PostgreSQL health check |
| `api/routes/schema.py` | Schema endpoint |
| `api/routes/admin.py` | Cache administration |
| `api/schemas/request.py` | Pydantic request and response models |
| `api/middleware/correlation.py` | Correlation ID creation and propagation |
| `api/middleware/logging.py` | HTTP request logging |
| `api/middleware/rate_limit.py` | In-process request rate limiting |
| `core/llm/ollama_client.py` | Ollama configuration, prompt context, generation, parsing and warmup |
| `core/llm/cloud_llm_client.py` | Cloud provider adapters |
| `core/schema/loader.py` | SQL DDL loading and schema prompt rendering |
| `core/rules/loader.py` | YAML business-rule loading and prompt rendering |
| `validation/validator.py` | SQL safety and AST validation |
| `execution/connection_pool.py` | asyncpg pool and read-only fetching |
| `execution/executor.py` | Query execution boundary |
| `monitoring/structured_logging.py` | Structured JSON logging and correlation enrichment |

## 6.4 SQL Validation and Read-Only Execution

The application validates model-generated SQL before sending it to PostgreSQL.

The current validator performs checks including:

- Rejecting empty SQL.
- Checking configured forbidden regex patterns.
- Parsing the statement using SQLGlot in PostgreSQL dialect.
- Rejecting multiple statements.
- Rejecting DML, DDL and command-like AST nodes.
- Blocking selected system-catalog references.
- Blocking configured forbidden identifiers and hazardous function names.
- Requiring an allowed top-level query shape (`SELECT` or `UNION`).
- Adding a top-level `LIMIT 1000` when the accepted query has no top-level limit.
- Serializing accepted SQL back into PostgreSQL SQL.

The executor then uses an asyncpg connection pool and a read-only transaction. Results are converted to dictionaries and truncated according to the configured result limit.

> Read-only transactions and AST checks are important safeguards, but they are not a substitute for database permissions, authentication, authorization, auditing and deployment-level security controls. See [Security and operational recommendations](#14-security-and-operational-recommendations).

## 6.5 Supported LLM Providers

The API accepts these provider identifiers:

| Provider | Integration |
|---|---|
| `ollama` | Local Ollama model (including a fine-tuned model registered with `ollama create`) |
| `openai` | OpenAI API |
| `gemini` | Google Gemini |
| `deepseek` | DeepSeek through an OpenAI-compatible client |
| `claude` | Anthropic Claude |

The default provider is `ollama`.

Cloud providers require the relevant API key and model configuration. Provider selection does not automatically configure credentials or download models.

## 6.6 Frontend Applications

### React frontend – `frontend-react/`

The primary data workspace includes:

- Natural-language query interface.
- Provider selection.
- Health/status indicators.
- Generated SQL inspection.
- Tabular query results.
- Visualization view.
- Table filtering and sorting.
- Pagination and CSV export.
- Query history and saved insights in browser `localStorage`.
- Schema browsing.
- Cache administration.

The Vite development server proxies `/api` requests to the backend. In the Docker deployment, Nginx forwards `/api/` requests to the backend.

---

# 7. Pipeline 2 – Installation and Configuration

## 7.1 Prerequisites

Install the following:

- Python compatible with the backend dependencies.
- Node.js **22.12 or later** for the current Vite frontend.
- npm.
- PostgreSQL reachable from the backend.
- Ollama, if using local inference.
- Docker Engine/Desktop and Docker Compose plugin, if using containers.

For cloud inference, configure the corresponding provider credentials instead of relying on a local Ollama model.

## 7.2 Configure Environment Variables

Create a root-level `.env` file in the application workspace.

```bash
cp .env.example .env
```

If the repository does not contain an `.env.example`, create `.env` manually using the variable reference below. Do not commit the real `.env` file.

### Backend and logging

| Variable | Purpose |
|---|---|
| `LOG_LEVEL` | Logging verbosity |
| `LOG_DIR` | Directory for log files |
| `SERVICE_NAME` | Service identifier in logs |
| `ENVIRONMENT` | Environment label |
| `HOSTNAME` | Host identifier |
| `DEV_MODE` | Development-mode setting |
| `CORS_ALLOWED_ORIGINS` | Allowed browser origins |

### Ollama

| Variable | Purpose |
|---|---|
| `OLLAMA_HOST` | Ollama server URL |
| `OLLAMA_MODEL` | Model name (may be a fine-tuned model registered in Ollama; see 5.6) |
| `OLLAMA_KEEP_ALIVE` | Model keep-alive duration |
| `OLLAMA_TEMPERATURE` | Generation temperature |
| `OLLAMA_MAX_TOKENS` | Maximum generated tokens |
| `OLLAMA_TOP_P` | Top-p sampling parameter |
| `OLLAMA_NUM_CTX` | Model context size |
| `OLLAMA_AUTO_WARMUP` | Whether to warm up Ollama during startup |

The documented default model is `qwen2.5-coder:7b`. If using another model, set `OLLAMA_MODEL` to the model installed in Ollama.

### PostgreSQL and connection pool

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Required presence/configuration check |
| `DATABASE_HOST` | PostgreSQL hostname |
| `DATABASE_PORT` | PostgreSQL port |
| `DATABASE_NAME` | Database name |
| `DATABASE_USER` | Database username |
| `DATABASE_PASSWORD` | Database password |
| `DB_POOL_MIN_SIZE` | Minimum pool size |
| `DB_POOL_MAX_SIZE` | Maximum pool size |
| `QUERY_TIMEOUT_SECONDS` | Query timeout |
| `MAX_RESULT_ROWS` | Maximum rows materialized by the fetch layer |

**Important implementation detail:** the current connection-pool initializer checks that `DATABASE_URL` is present, but creates the asyncpg pool using the separate host, port, user, password and database variables. Configure all of them consistently.

### Rate limiting

| Variable | Purpose |
|---|---|
| `RATE_LIMIT_PER_MINUTE` | Maximum in-process requests per client per minute |

### Cloud providers

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | OpenAI API credential |
| `OPENAI_MODEL` | OpenAI model |
| `GEMINI_API_KEY` | Gemini API credential |
| `GEMINI_MODEL` | Gemini model |
| `DEEPSEEK_API_KEY` | DeepSeek API credential |
| `DEEPSEEK_MODEL` | DeepSeek model |
| `DEEPSEEK_BASE_URL` | Optional DeepSeek API base URL |
| `ANTHROPIC_API_KEY` | Anthropic API credential |
| `ANTHROPIC_MODEL` | Claude model |
| `CLOUD_LLM_TEMPERATURE` | Cloud generation temperature |
| `CLOUD_LLM_MAX_TOKENS` | Cloud output token limit |

### Frontend configuration

| Variable | Purpose |
|---|---|
| `VITE_API_BASE` | Optional browser-accessible API base URL for React |


## 7.3 PostgreSQL Configuration

The application expects a PostgreSQL database reachable from the backend.

Before starting the application:

1. Start the PostgreSQL server/container.
2. Confirm that the configured database exists.
3. Confirm that the configured user can connect.
4. Confirm that the user has only the permissions required by the application.
5. Confirm that the database host is reachable from the backend's execution environment.

For local development, `localhost` may be appropriate when PostgreSQL runs on the same host.

For Docker, `localhost` inside the backend container refers to that container. Use the appropriate Docker service/container hostname or `host.docker.internal` when the database runs on the host and the Compose environment supports that mapping.

The application configures the PostgreSQL session search path to `public`.

## 7.4 Ollama Configuration

Start Ollama:

```bash
ollama serve
```

In a separate terminal, download the configured model. For the documented default:

```bash
ollama pull qwen2.5-coder:7b
```

If using a fine-tuned model produced by Pipeline 1.5, register it per [5.6](#56-gguf-export-and-ollama-registration) and set `OLLAMA_MODEL` accordingly.

Confirm the model is available:

```bash
ollama list
```

Confirm that the Ollama server responds:

```bash
curl http://localhost:11434/api/tags
```

Set `OLLAMA_HOST` to the Ollama endpoint reachable from the backend. When the backend is inside Docker and Ollama runs on the host, do not use the container's own `localhost`; use a host-reachable address such as `host.docker.internal` where supported.

## 7.5 Cloud Provider Configuration

If using a cloud provider:

1. Add the relevant API key to the root `.env`.
2. Set the matching provider model variable.
3. Ensure the backend environment can reach the provider API.
4. Select the provider in the frontend or include it in the API request.

Do not place API keys in frontend source code or expose them through Vite variables.

---

# 8. Running Pipeline 2 Locally

Run the backend and frontend in separate terminals. PostgreSQL and the selected model provider must already be reachable.

## 8.1 Start the Backend

From the application root
Create a virtual environment:

**Windows PowerShell**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install backend dependencies:

```bash
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

Start FastAPI:

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Backend endpoints:

- API root: `http://localhost:8000/`
- Interactive API documentation: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/health`

## 8.2 Start the React Frontend

Open another terminal:

```bash
cd frontend-react
```

Check Node:

```bash
node --version
```

Use Node 22.12 or later.

Install the lockfile-pinned dependencies:

```bash
npm ci
```

Start Vite:

```bash
npm run dev
```

Open:

```text
http://localhost:3000
```

The Vite configuration proxies `/api` requests to `http://localhost:8000`. Keep the default API base unless the backend is running at a different browser-accessible address.


## 8.3 Verify the Installation

### Check backend health

```bash
curl -i http://localhost:8000/api/health
```

Expected healthy response:

```json
{
  "status": "healthy",
  "postgres": "connected"
}
```

This endpoint verifies PostgreSQL connectivity. It does not verify that Ollama is ready.

### Check the API root

```bash
curl -fsS http://localhost:8000/ 
```

### Check the schema endpoint

```bash
curl -i http://localhost:8000/api/schema
```

Review the response carefully. With the current checked-in configuration mismatch, this endpoint may return an empty object.

### Submit a test query

```bash
curl -i -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"Return a single row containing the number 1\",\"provider\":\"ollama\"}"
```

A successful response contains:

```json
{
  "sql": "SELECT 1 LIMIT 1000",
  "results": [
    {
      "?column?": 1
    }
  ],
  "row_count": 1,
  "correlation_id": "request-id"
}
```

The exact generated SQL and returned column name depend on the model and PostgreSQL serialization. Treat the example as an illustration of the response shape.

### Check request validation

```bash
curl -i -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"\",\"provider\":\"ollama\"}"
```

An empty query is expected to fail request validation with HTTP `422`.

### Validate the React UI

At `http://localhost:3000`:

1. Open the Ask Data workspace.
2. Confirm the API/database status is displayed.
3. Submit a natural-language question.
4. Inspect the generated SQL and result rows.
5. Switch between Visualization, Table, SQL and Details.
6. Try filtering, sorting, pagination and CSV export.
7. Save an insight and reopen it from Saved Insights.
8. Open SQL Inspection.
9. Exercise Data Sources and Administration.

Query history and saved insights are stored in browser `localStorage`; they are not shared across browsers or users.

---

# 9. Running Pipeline 2 with Docker Compose

## 9.1 Build and Start Services

Ensure Docker Engine/Desktop and the Compose plugin are running.

From the application root,

Validate the Compose configuration:

```bash
docker compose config --quiet
```

Build and start the backend and React frontend:

```bash
docker compose up --build -d backend frontend_react
```

Check the containers:

```bash
docker compose ps
```

The default React deployment is available at:

```text
http://localhost:3000
```

The backend is exposed at:

```text
http://localhost:8000
```

## 9.2 View Logs and Service Status

Follow backend and React frontend logs:

```bash
docker compose logs -f backend frontend_react
```

View only backend logs:

```bash
docker compose logs -f backend
```

View service status:

```bash
docker compose ps
```

Stop following logs with `Ctrl+C`. This does not stop the containers.

## 9.3 Start Frontend

To build and start the backend and frontend:

```bash
docker compose up --build -d \
  backend \
  frontend_react \
```

Service URLs:

| Service | Host URL |
|---|---|
| React frontend | `http://localhost:3000` |
| FastAPI backend | `http://localhost:8000` |

## 9.4 Stop and Restart Services

Stop the application services without removing containers:

```bash
docker compose stop backend frontend_react
```

Restart them:

```bash
docker compose start backend frontend_react
```

Stop and remove the Compose containers and network:

```bash
docker compose down
```

Rebuild after source or dependency changes:

```bash
docker compose up --build -d backend frontend_react
```

`docker compose down` does not imply that independently managed PostgreSQL or Ollama services are stopped. Review the actual Compose service definitions before assuming which dependencies are included.

## 9.5 Container Networking

Inside a container, `localhost` refers to that container itself.

Typical connectivity:

| Backend location | Dependency location | Address pattern |
|---|---|---|
| Local Python process | Local PostgreSQL | `localhost` |
| Backend container | PostgreSQL Compose service | Service/container DNS name |
| Backend container | PostgreSQL on host | `host.docker.internal` where supported |
| Backend container | Ollama on host | `host.docker.internal` where supported |
| Frontend container | Backend Compose service | `http://backend:8000` |

The Compose configuration provides a host-gateway mapping for the backend. Verify the actual `.env` values and service network before starting the application.

---

# 10. REST API Reference

The backend routes are registered under the `/api` prefix unless otherwise noted.

## 10.1 Health Check

**Endpoint**

```http
GET /api/health
```

**Example**

```bash
curl http://localhost:8000/api/health
```

**Response shape**

```json
{
  "status": "healthy",
  "postgres": "connected"
}
```

The status is based on the database connection-pool connectivity check.

## 10.2 Query Endpoint

**Endpoint**

```http
POST /api/query
```

**Request body**

```json
{
  "query": "Show the total number of orders",
  "provider": "ollama"
}
```

`provider` is optional and defaults to `ollama`.

Supported values:

- `ollama`
- `openai`
- `gemini`
- `deepseek`
- `claude`

**Success response shape**

```json
{
  "sql": "SELECT COUNT(*) FROM orders LIMIT 1000",
  "results": [
    {
      "count": 125
    }
  ],
  "row_count": 1,
  "correlation_id": "request-id"
}
```

**Example request**

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"Show the total number of orders\",\"provider\":\"ollama\"}"
```

**Response fields**

| Field | Description |
|---|---|
| `sql` | Validated SQL statement |
| `results` | Array of result-row objects |
| `row_count` | Number of returned rows |
| `correlation_id` | Request correlation identifier |

**Common status codes**

| HTTP status | Meaning |
|---|---|
| `200` | Query completed successfully |
| `400` | SQL rejection or generation/validation/execution error |
| `422` | Request body validation failure |
| `429` | Rate limit exceeded |

The error response generally contains a `detail` field and may contain a `correlation_id`, depending on the error path.

## 10.3 Schema Endpoint

**Endpoint**

```http
GET /api/schema
```

Returns the schema currently loaded by the backend's `SchemaLoader`.

The endpoint is only as complete as the SQL DDL files successfully loaded from `config/schemas/`.

## 10.4 Cache and Administration Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/cache/warmup` | Warm up the Ollama model/context |
| POST | `/api/cache/invalidate` | Invalidate the combined static context |
| POST | `/api/admin/cache/refresh` | Invalidate/rebuild context and warm Ollama |
| POST | `/api/admin/cache/clear` | Clear combined context and conditionally warm |
| POST | `/api/admin/cache/warmup` | Warm up the Ollama cache |

These routes are administrative operations, but the checked-in backend does not implement authentication or authorization for them. Do not expose them to an untrusted network without adding access controls.

---

# 11. Caching, Logging and Monitoring

## 11.1 Static Prompt Context

The local Ollama client uses a singleton static-context builder. It combines the system prompt, loaded schema text, loaded business-rule text, hard-coded examples and generic SQL guidance.

The combined context is cached in process memory. This avoids rebuilding the same static prompt context for every request.

## 11.2 Ollama Keep-Alive and Warmup

Ollama generation uses configured model options and a keep-alive value. Startup can optionally perform a short warmup request, controlled by `OLLAMA_AUTO_WARMUP`.

The cache endpoints provide explicit warmup and context invalidation operations.

The implementation's cache invalidation only clears the combined context string. It does not necessarily reload the schema and business-rule loader caches from disk. Restart the backend process after changing those source files if a reliable reload is required.

## 11.3 Structured Logging

The logging layer emits structured JSON logs with fields such as:

- Timestamp.
- Severity.
- Logger and message.
- Service and environment.
- Hostname.
- Correlation ID.
- Request method and path.
- Request status and contextual metadata.

The correlation middleware accepts an incoming `X-Correlation-ID` or creates a UUID and returns it in the response header. This allows a request to be traced across the API and execution logs.

The logger configures console output, a general JSON log file and an error-only JSON log file.

Protect log files: the current query route logs a question prefix and generated SQL, and some validator warnings may include SQL text.

## 11.4 Rate Limiting

The rate limiter uses an in-memory sliding 60-second window. The documented default is 100 requests per client per minute.

It is process-local and is not shared across multiple workers or replicas. It is not a replacement for a distributed rate limiter or gateway-level protection.

---

# 12. End-to-End Usage Example

This example illustrates the normal user workflow after the database, backend and model provider are configured.

**Step 1 – Start dependencies**

- Start PostgreSQL.
- Start Ollama or configure a cloud provider. If using a fine-tuned model from Pipeline 1.5, ensure it has been registered with Ollama per [5.6](#56-gguf-export-and-ollama-registration).
- Confirm that the backend can reach both dependencies.

**Step 2 – Start the backend**

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Step 3 – Start the frontend**

```bash
cd frontend-react
npm run dev
```

**Step 4 – Open the application**

```text
http://localhost:3000
```

**Step 5 – Ask a business question**

For example:

```text
Show the total number of orders by order status.
```

**Step 6 – Review the generated SQL**

Inspect the SQL shown by the application. Confirm that the selected tables, joins, filters and aggregation correspond to the intended business question.

**Step 7 – Review the results**

Inspect the returned rows in the table view and use the visualization view when the result structure is suitable.

**Step 8 – Trace a request if needed**

Use the correlation ID returned by the API to locate the corresponding backend log entries.

---

# 13. Troubleshooting

| Symptom | Likely cause | Checks / corrective action |
|---|---|---|
| Backend starts but health is unhealthy | PostgreSQL is unreachable or pool initialization failed | Check all database environment variables, credentials, host/port and backend logs |
| `DATABASE_URL` configuration error | Required presence check fails | Set `DATABASE_URL` as well as the separate connection fields |
| Connection refused to PostgreSQL | Incorrect host/port or database service is stopped | Test connectivity from the same environment as the backend |
| Docker backend cannot connect to host PostgreSQL | Container uses its own `localhost` | Use a reachable host address or Docker service hostname |
| Ollama connection error | Ollama is not running or host is incorrect | Run `ollama serve`; verify `OLLAMA_HOST` from the backend environment |
| Model not found | Configured model is not installed | Run `ollama list` and pull the configured model |
| Fine-tuned model not found | Ollama model not registered | Register GGUF per [5.6](#56-gguf-export-and-ollama-registration) and set `OLLAMA_MODEL` |
| Frontend says API is unreachable | Backend is stopped or proxy/API base is incorrect | Check port 8000, Vite proxy configuration and browser Network tab |
| Query returns HTTP 400 | Model generation, SQL validation or database execution failed | Inspect response `detail` and backend logs using the correlation ID |
| Query returns HTTP 422 | Invalid request body | Ensure `query` is a non-empty string and provider is supported |
| Query returns HTTP 429 | Per-process request limit reached | Wait for the window to expire or review rate-limit configuration |
| Schema endpoint returns `{}` | Expected DDL files are absent or not parsed | Check `config/schemas/*.sql` |
| Business rules do not appear in prompt | Expected YAML file is absent or incompatible | Check `config/rules/business_rules.yaml` |
| Context changes are not reflected | Loader-level caches remain in memory | Restart the backend after changing schema/rule source files |
| React dependency install fails | Node/npm version or lockfile issue | Use Node 22.12+ and run `npm ci` |
| Docker frontend waits for backend | Backend health check is failing | Inspect `docker compose ps` and backend logs |
| Fine-tuning script reports missing data file | File is named `nl2sql_train.jsonl` instead of `nl2sql_train_llm_refined.jsonl` | Copy or regenerate under the expected name; see [15.13](#1513-fine-tuning-artifact-boundary) |
| `save_pretrained_gguf` produces no `.gguf` at requested path | Converter writes to `<export_dir>_gguf/` sibling | Copy the `.gguf` from the `_gguf` directory |
| Training fails with "tokenizer has no usable chat template" | Base checkpoint is not an Instruct/chat model | Use a chat checkpoint or supply a template |

---

# 14. Security and Operational Recommendations

The current implementation includes useful safeguards, but a production deployment should add or verify the following controls.

1. **Use a dedicated read-only database account.** Do not rely solely on generated-SQL validation to prevent writes.
2. **Keep credentials out of source control.** Store `.env` securely and restrict access to deployment secrets.
3. **Add authentication and authorization.** The checked-in API and cache administration endpoints do not have authentication middleware.
4. **Restrict network exposure.** Do not expose PostgreSQL, Ollama or administrative endpoints publicly without appropriate network controls.
5. **Use TLS where appropriate.** Protect traffic between browsers, API services, model providers and databases.
6. **Protect logs.** Queries and generated SQL may contain business-sensitive data. Apply access controls, retention limits and redaction.
7. **Review SQL before production use.** The validator's current checks do not constitute a complete database authorization policy.
8. **Use a non-production database for initial testing.** Validate prompts, schema mapping, SQL generation and result correctness before connecting sensitive data.
9. **Add distributed rate limiting.** The current limiter is process-local and does not coordinate multiple workers.
10. **Monitor dependency readiness.** Successful application startup does not prove that PostgreSQL, the model provider or schema context is ready.
11. **Add automated tests.** The inspected source tree does not contain a checked-in test suite.
12. **Review result limits.** The validator's injected limit and the database fetch truncation are separate controls; neither should be treated as a complete query-cost policy.
13. **Treat fine-tuned model artifacts as sensitive.** LoRA adapters and GGUF exports may encode domain-specific business knowledge; store them in controlled artifact repositories and avoid publishing adapters trained on proprietary schemas.
14. **Validate data used for fine-tuning.** Training data is derived from real business questions and SQL; review for sensitive content before committing datasets to source control or shared storage.

---

# 15. Known Limitations and Configuration Checks

The following are important observations about the checked-in application configuration. They should be resolved or explicitly accepted before relying on the corresponding functionality.

Fine-tuning-specific limitations are documented in [5.8](#58-fine-tuning-specific-limitations). This section covers the runtime application and its integration boundary with Pipeline 1.

## 15.1 Schema Loader Path Mismatch

The backend's `SchemaLoader` expects SQL DDL files at:

```text
config/schemas/*.sql
```

The checked-in repository instead contains:

```text
config/schema.json
```

The current loader does not consume that JSON file. Consequently, `/api/schema` can return an empty object and the LLM prompt may not receive the intended database schema.

**Required action:** provide SQL DDL files at the path expected by the loader, or intentionally update the loader to parse the JSON schema. Ensure the resulting prompt schema matches the target database.

## 15.2 Business-Rule Loader Path and Format Mismatch

The backend's `RulesLoader` expects:

```text
config/rules/business_rules.yaml
```

The checked-in repository instead contains:

```text
config/business_rules.json
```

The JSON file is not consumed by the current YAML loader and has a different structure from the loader's supported rule format.

**Required action:** provide a compatible YAML file at the expected path, or update the loader and its data model to support the JSON representation.

## 15.3 Hard-Coded Few-Shot Examples

The Ollama prompt builder includes hard-coded examples across several business domains. Some example table names do not match the checked-in JSON schema.

This can introduce conflicting schema signals into the prompt.

**Required action:** align few-shot examples with the target database and business domain.

## 15.4 Date Guidance Inconsistency

The system prompt instructs the model to use literal date values rather than dynamic date functions, while some hard-coded examples use `CURRENT_DATE` or similar expressions. The validator does not currently prohibit those date functions.

**Required action:** make the prompt examples and date-handling policy consistent.

## 15.5 Cache Refresh Does Not Fully Reload Source Files

The combined-context cache can be invalidated, but the schema and rules loaders retain their own in-memory caches. A cache refresh may therefore reuse already-loaded data.

**Required action:** restart the backend after changing schema or business-rule source files unless loader-level reload behavior is implemented.

## 15.6 Startup Can Be Partially Degraded

Database initialization and Ollama/context initialization catch and log many failures. The API process may therefore start even when one or more dependencies are not ready.

**Required action:** verify `/api/health`, Ollama connectivity and schema/rule loading independently.

## 15.7 Health HEAD Endpoint

The current `HEAD /api/health` implementation accesses the returned health dictionary using attribute-style access. This can raise an `AttributeError`.

Use `GET /api/health` for the documented health check until the HEAD handler is corrected.

## 15.8 Authentication and Authorization

No authentication middleware is present in the checked-in backend. This includes query and cache administration routes.

**Required action:** add appropriate identity, authorization and administrative access controls before exposing the application beyond a trusted development environment.

## 15.9 Rate Limiting Is Process-Local

The rate limiter stores request timestamps in memory. Different backend workers or replicas do not share a common counter.

**Required action:** use a shared store or API gateway if consistent multi-worker/multi-instance rate limiting is required.

## 15.10 SQL Validation Boundaries

The AST validator blocks selected statement types and catalog/function patterns, but it does not compare every referenced business table against a configured allow-list.

**Required action:** use database-level least privilege and consider table/schema allow-list validation as an additional control.

## 15.11 Error and Logging Exposure

The query route can return exception text and processing-stage details to callers. Query prefixes and generated SQL are also logged.

**Required action:** review error redaction and logging policies before handling sensitive production data.

## 15.12 Pipeline Integration Boundary

Pipeline 1 exports `schema.json` and `context.json`. Pipeline 2's current loaders expect SQL DDL and YAML business rules at separate locations.

Therefore, Pipeline 1 outputs should not be assumed to flow directly into Pipeline 2 without a conversion step or loader changes.

**Required action:** define and test an explicit artifact contract between the pipelines. At minimum, agree on schema representation, business-rule representation, file paths and reload behavior.

## 15.13 Fine-Tuning Artifact Boundary

Pipeline 1's dataset generator emits `nl2sql_train.jsonl`, `nl2sql_dev.jsonl`, `nl2sql_test.jsonl`, and `context.json`. Pipeline 1.5's trainer (`train_qlora_unsloth.py`) hard-codes the input path `data/nl2sql_train_llm_refined.jsonl`.

The following mismatches exist between the two workspaces:

1. **Training filename.** The trainer does not read `nl2sql_train.jsonl`; it reads `nl2sql_train_llm_refined.jsonl`. Pipeline 1 users must rename, copy, or regenerate the train split under the expected name. See [5.2](#52-input-artifact-contract) and [5.8 item 1](#58-fine-tuning-specific-limitations).
2. **Directory layout.** Pipeline 1 outputs land under `out/`; the trainer expects a `data/` directory. A copy step is required, or the trainer's `--data-dir` must be pointed at the Pipeline 1 output directory.
3. **Prompt shape mismatch.** The trainer's prompts use the `DOMAIN AND BUSINESS CONTEXT` + `RELEVANT DATABASE SCHEMA` + `QUESTION` structure derived from `context.json`. Pipeline 2's runtime prompt uses the schema and rule loaders described in 15.1 and 15.2. If these diverge, fine-tuned accuracy gains are lost at inference time.

**Required action:** either (a) add a copy/rename step between pipelines, (b) accept `--data-dir` pointing at Pipeline 1's output and rename the train split, or (c) update the trainer and Pipeline 2 loaders to share a canonical artifact layout. Validate prompt shape consistency before drawing conclusions from fine-tuning results.

---

# 16. Development Guidelines

When modifying the application:

- Trace the complete request path from the frontend to `backend/api/routes/query.py`, the LLM adapter, validator, executor and connection pool.
- Preserve the Pydantic request/response contract unless all affected frontends are updated together.
- Keep SQL validation and read-only database execution aligned.
- Do not assume that a successful backend startup proves dependency readiness.
- Test local and Docker connectivity separately; `localhost` has different meanings in host and container environments.
- Keep provider credentials and database secrets outside source control.
- Keep schema metadata and business definitions synchronized with the actual database.
- Restart the backend when changing source files that are cached in singleton loaders.
- Add regression tests for SQL parsing, prohibited statements, provider response parsing and database execution.
- Record reproducible dataset-generation settings, including template tier, seed and verification flags.
- When changing the fine-tuning prompt template in `train_qlora_unsloth.py` (`build_text()`), verify Pipeline 2's runtime prompt still matches its shape; otherwise the fine-tuned adapter will be used out-of-distribution at inference time.
- Never evaluate on `nl2sql_test.jsonl` during hyperparameter search; treat it as a held-out split and only evaluate against it after decisions are frozen.
- Track the exact input filenames consumed by `train_qlora_unsloth.py` when refactoring Pipeline 1's dataset exporter, so the `nl2sql_train_llm_refined.jsonl` contract does not silently break.

---

# 17. Outputs and Deliverables

## Pipeline 1

| Stage | Deliverable | Purpose |
|---|---|---|
| Schema extraction | `schema.json` | Database structure, relationships and profiles |
| Context builder | `context.json` | Primary enriched business context |
| Context builder | `context.review.json` | Review flags and lower-confidence fields |
| Context builder | `terminology_map.tsv` | Business terminology lookup |
| Dataset generator | `nl2sql_train.jsonl` | Training partition |
| Dataset generator | `nl2sql_dev.jsonl` | Development/validation partition |
| Dataset generator | `nl2sql_test.jsonl` | Held-out test partition |
| Dataset generator | `dataset_manifest.json` | Generation metadata and split counts |

## Pipeline 1.5

| Stage | Deliverable | Purpose |
|---|---|---|
| Fine-tuning | `outputs/nl2sql-qlora/final_adapter/` | LoRA adapter weights and tokenizer |
| Fine-tuning | `outputs/nl2sql-qlora/run_metadata.json` | Reproducibility metadata (base model, epochs, LoRA rank, split counts) |
| Fine-tuning | `outputs/nl2sql-qlora/checkpoint-*/` | Training checkpoints (subject to `save_total_limit`) |
| Export | `<Model>.Q4_K_M.gguf` | Quantized model for Ollama |
| Deployment | Ollama model (e.g., `nl2sql-finetuned`) | Served to Pipeline 2 via `OLLAMA_MODEL` |

## Pipeline 2

| Component | Output |
|---|---|
| Query API | Validated SQL, result rows, row count and correlation ID |
| Health API | Application/database health information |
| Schema API | Loaded schema representation |
| React UI | Interactive query workspace and result views |
| Logging | Structured JSON request and application logs |

---

# 18. Future Improvements

The following are potential improvements rather than claims about current functionality:

1. **Unified pipeline artifact contract:** make Pipeline 1 schema/context exports directly consumable by Pipeline 2, and align the fine-tuning trainer's expected filenames with Pipeline 1's actual exports.
2. **Schema-aware validation:** verify generated SQL references against the actual loaded schema and permitted tables.
3. **Authentication and role-based access:** secure query and administrative endpoints.
4. **Distributed rate limiting:** use Redis or an API gateway for multi-worker deployments.
5. **Asynchronous model calls:** avoid blocking the FastAPI event loop during local model generation.
6. **Improved health/readiness probes:** report database, model and context readiness independently.
7. **Automated regression evaluation:** measure exact match, execution success, result correctness, latency and invalid-query rates.
8. **Observability:** expose metrics for request volume, latency, model generation, validation failures and database execution.
9. **Prompt/version management:** version schema context, business rules and few-shot examples for reproducible behavior.
10. **Expanded test coverage:** add unit, integration and end-to-end tests for both pipelines.
11. **Automated evaluation of fine-tuned adapters** against `nl2sql_test.jsonl` (exact SQL match, execution success, result equivalence) before promotion.
12. **Packaging for fine-tuning inputs:** a fixture or `make prepare-finetuning-data` step that maps Pipeline 1's `nl2sql_train.jsonl` → `nl2sql_train_llm_refined.jsonl` and copies `context.json` into `nl2sql-finetuning/data/`.
13. **GGUF export helper:** a small script or Makefile target that copies the `_gguf/` sibling output to a stable path and generates a Modelfile when Unsloth skips it.

---

## License and Usage

Add the applicable license, ownership, attribution and usage restrictions for this project before public distribution.

## Maintainer Notes

This README is intended to serve as the main technical entry point for developers setting up, running, evaluating and maintaining the pipelines (Pipeline 1, Pipeline 1.5 fine-tuning, and Pipeline 2). Keep it synchronized with actual source-code paths, environment variables, CLI flags and deployment configuration as the implementation evolves.
