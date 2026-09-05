# FiFi — Financial Findings

An AI assistant for asking plain-language questions about financial operations data and receiving accurate, traceable answers. Built for the **TBX - BVP Tech Catalyst Hackathon**.

Start with the [documentation map](docs/README.md). For the complete component breakdown, request flow, design rationale, tradeoffs, security analysis and prioritized limitations, read [Architecture Deep Dive](docs/ARCHITECTURE.md).

> **Data status:** local CSVs are sample-ingestion inputs only. The running assistant always discovers and queries the connected MySQL database directly. The real high-volume TBX database is never copied to CSV.


## Columns we compute

TBX ships three tables. Four columns on the `transaction` view are **derived by
this application**, not supplied by TBX, and are documented here so nothing is
mistaken for source data:

| Column | Derivation | Why |
|---|---|---|
| `debit_amount` / `credit_amount` | split of `transaction_amount` by `transaction_type` | "spend" means debits; summing `transaction_amount` adds money in to money out |
| `signed_amount` | debits negated | net movement in one column |
| `reconciliation_status` | no reference number and no UTR → `unreconciled`; one of the two missing → `partially_reconciled` | the schema has no reconciliation column, and the assistant states this definition in every answer that relies on it |

`account_number` and `utr_number` never leave the source layer: the public views
expose `account_last4` and a boolean `utr_available` instead.

## What the starter already supports

- Durable, bounded multi-turn history with deterministic follow-up plan merging
- CSV-to-MySQL ingestion for the local sample database
- Cached live-schema discovery through MySQL `INFORMATION_SCHEMA`
- Final-schema semantic views with deterministic bank/account joins
- Account-number masking and complete UTR exclusion from chat and exports
- Model-generated structured query plans constrained to real datasets and columns
- Deterministic, parameterized filtering, grouping and aggregation in MySQL
- Read-only runtime credentials, optional replica endpoint and per-session query timeout
- Explicit list projections, mandatory time scope for broad transactions and bounded evidence
- Runtime `EXPLAIN FORMAT=JSON` cost guard; opt-in `EXPLAIN ANALYZE` benchmark mode
- Plain-language explanations generated only after computation
- Evidence tables containing the underlying records or breakdown
- CSV export for every computed result
- Explicit clarification instead of fabricated figures
- Bounded clarification loop with selectable field/value choices and type-ahead search
- Cached semantic aliases and a top-3-table/top-20-column planner context
- Confidence signalling based on whether matching evidence exists
- Mock mode for developing without API credits
- Replaceable model provider, initially wired for Sarvam AI

The TBX relationship is `bank 1—N account 1—N transaction`. The language model queries only safe semantic views; it never generates joins or sees the raw sensitive columns.

## Included synthetic demo data

Place the local sample CSVs in `data/uploads/`. The Compose seed job imports them into private `source_*` MySQL tables and creates privacy-safe query views. CSV is not used in the chat request path.

Try these immediately in mock mode:

- `How much was debited last month?`
- `Show transactions for bank code HDFC last month.`
- `Break down available balance by bank.`
- `Find transaction reference ID REF-SYN-0005.`

Mock mode uses a deliberately small rule-based planner for these acceptance paths. It exists for local plumbing tests, not as the final natural-language model.

Generate a larger deterministic dataset without extra dependencies:

```bash
python scripts/generate_dummy_data.py --accounts 10000 --transactions 1000000
```

Then place the generated files in the configured `SEED_DIRECTORY`. Generated data is gitignored. Capacity
assumptions and scaling thresholds are documented in
[Capacity Estimation](docs/architecture/CAPACITY_ESTIMATION.md).

## Grounded request flow

```mermaid
flowchart LR
    A[React chat] --> B[FastAPI]
    B --> C[Lightweight LLM planner]
    C --> D[Validated query plan]
    D --> E[MySQL calculation]
    E --> F[Evidence rows]
    F --> G[Deterministic narration]
    G --> A
```

The language model never calculates totals or writes the final figures. It maps the question to a constrained `QueryPlan`; the backend validates dataset and column names, parameterizes filter values, runs the calculation, reconciles grouped evidence, and renders the answer deterministically. The server retains only the latest 12 compact messages and the last validated plan. Evidence rows are never copied into conversational memory.

Ambiguous fields or dimension values pause execution and return up to eight
choices. The partial plan is stored server-side; choosing an option resumes it
without another model call. A debounced search endpoint retrieves further safe
values with bounded, cost-checked prefix queries, so candidate lists never enter
the model prompt. The loop stops after two clarification rounds.

## Repository structure

```text
frontend/                 React + TypeScript chat and evidence UI
backend/app/api/          Chat, upload, catalog and export endpoints
backend/app/assistant/    Planning and grounded explanation workflow
backend/app/data/         MySQL introspection, sample ingestion and deterministic query engine
backend/app/providers/    Mock and Sarvam model adapters
backend/app/tools/        Extension point for problem-specific tools
backend/tests/            Guardrail and computation tests
data/uploads/             Local sample-ingestion CSVs only; contents are gitignored
```

## Start locally

Prerequisite: Docker Desktop with the Docker engine running.

```bash
git clone https://github.com/MenigStar91/tbx-ai-assistant.git
cd tbx-ai-assistant
cp .env.example .env
docker compose up --build
```

Open the UI at http://localhost:5173, API docs at http://localhost:8000/docs,
health endpoint at http://localhost:8000/api/v1/health, and the judge-friendly
system contract at http://localhost:8000/api/v1/info.

The default `LLM_PROVIDER=mock` requires no API key and demonstrates the grounded path with a basic count plan. For meaningful natural-language planning, configure the model selected after TBX shares its model-efficiency guidance.

## Configure Sarvam AI

Set these values in `.env` without committing the file:

```env
LLM_PROVIDER=sarvam
SARVAM_API_KEY=your_key
SARVAM_MODEL=sarvam-105b
```

The provider interface is deliberately replaceable. The final lightweight model should be chosen only after the model-efficiency scoring note and capped credits are provided. A locally hosted model can be added as another `LLMProvider` without changing the assistant workflow.

## Load the local sample database

Put the supplied sample CSVs in `data/uploads/` before the first `docker compose up`, use the UI, or call:

```bash
curl -X POST http://localhost:8000/api/v1/datasets/upload \
  -F 'files=@bank.csv' \
  -F 'files=@account.csv' \
  -F 'files=@transaction.csv'
```

The importer retains the files locally, loads them into MySQL, creates safe views and refreshes the catalog. Inspect it at `GET /api/v1/datasets`.

For the real database, configure `MYSQL_READ_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`,
`MYSQL_READ_USER` and `MYSQL_READ_PASSWORD`, then run the API without the local
`seed` service. Point `MYSQL_READ_HOST` at a read replica when TBX provides one;
otherwise it can target the primary through the same interface. Do not give the
runtime user write privileges. `MYSQL_WRITE_*` is used only by the local seed job.
Schema extraction reads metadata only and is cached. After an approved DDL change,
call `POST /api/v1/datasets/refresh`.

Every runtime query is checked with cost-only `EXPLAIN FORMAT=JSON`, bounded by
`MYSQL_QUERY_TIMEOUT_MS`, and refused when its estimated cost exceeds
`MYSQL_MAX_QUERY_COST`. Broad `transaction` queries require a date/time filter;
exact transaction/reference lookups are exempt. List plans project only requested
safe columns, and raw evidence or grouped output is capped by `MAX_RESULT_ROWS`.
For a controlled performance run—not normal requests—set
`MYSQL_EXPLAIN_ANALYZE=true`; remember that MySQL then executes the explained query.

## Sample questions for the final submission

These are acceptance-test prompts from the stated scope. Actual answers must be captured only after running them against the official dataset.

1. How much was debited last month?
2. Break down available balance by bank.
3. Show transactions for HDFC Bank last month.
4. Find transaction reference ID REF-SYN-0005.
5. Show transactions for the account ending in 2345 last month.
6. Export that breakdown as CSV.

Do not place placeholder numeric answers in the final presentation. Save the exact question, generated query plan, evidence and response from a reproducible run.

## Evaluation alignment

| Criterion | Implementation |
|---|---|
| Accuracy and grounding | Allowlisted query plans, parameterized filters and deterministic MySQL computation |
| Model efficiency | Replaceable provider; model choice deferred until official scoring guidance arrives |
| Natural-language understanding | Model translates intent, filters, dates and follow-up context into structured plans |
| Functionality | Chat, upload, query, evidence and export endpoints |
| User experience | Evidence shown inline with confidence and one-click CSV export |
| Explainability | Dataset, calculation summary, columns and source rows returned with every answer |
| Hallucination control | Missing data, invalid columns and ambiguous questions return clarification rather than a number |

The final model scorecard measures answer accuracy, exact intent/query-plan
generation, correct refusals, evidence fidelity, tokens and P95 latency. Current
results are deliberately marked pending after the schema change; see
[Model Scorecard](docs/evaluation/MODEL_SCORECARD.md) and [Evaluation Status](EVAL.md).

## Data and reconciliation boundaries

Complex bank/account/transaction questions use fixed semantic joins; the LLM
never generates join SQL. Vendor questions currently identify the missing
vendor mapping. Double-entry reconciliation requires immutable journal lines,
which are not present in the published schema. The required atomic ingest,
quarantine and issue workflow is specified in
[Reconciliation and Ingestion](docs/data/RECONCILIATION.md).

## Hack-day checklist

1. Import the provided sample CSVs into local MySQL or connect the read-only TBX database user.
2. Check discovered names and types at `/api/v1/datasets`.
3. Add aliases only where the official data dictionary requires them.
4. Benchmark the permitted lightweight model on a fixed question set.
5. Add date-range tests using dates present in the dataset.
6. Capture sample questions, query plans, source records and exact answers.
7. Add anomaly detection only after grounding tests pass.
8. Prepare the required architecture diagram and presentation deck.

## Known starter limitations

- CSV import exists only for constructing the local sample database; the real source must be MySQL-compatible
- The generic catalog discovers new tables and columns, while cross-table business joins still require approved database views
- Sample covering indexes match the demo paths; production indexes require TBX workload evidence and `EXPLAIN ANALYZE`
- A columnar warehouse/replica is the production scaling path for large analytical scans, not a demo dependency
- UTR plaintext lookup is intentionally unsupported because the source may encrypt it
- In-memory exports expire when the API restarts
- Conversation sessions are keyed by an unguessable UUID; authentication and tenant ownership must be added before production use
- One message produces one query plan; independent multi-question batching is not supported
- Mock mode validates plumbing, not language understanding
- Authentication and multi-tenancy are intentionally excluded by the problem scope
- Model choice and accuracy metrics remain open pending TBX guidance and credits

## Testing

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Tests cover deterministic calculations and refusal to answer without uploaded data. Add golden question-plan-answer cases once the official dataset arrives.

## PR review agent

The repository includes the shared `$tbx-pr-reviewer` skill under `.agents/skills/`. Use it with a GitHub pull request URL or number:

```text
Use $tbx-pr-reviewer to review PR #12.
Use $tbx-pr-reviewer to fix the verified findings in PR #12.
```

Review mode is read-only by default. Fix mode changes only the PR branch after an explicit request, runs relevant verification, and never merges automatically.

## License

Private and confidential. See [LICENSE](LICENSE). Confirm the hackathon's ownership and submission terms before replacing it with an open-source license.
