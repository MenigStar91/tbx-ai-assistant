# TBX Finance Assistant - Architecture Deep Dive

## 1. Executive summary

The system is a grounded natural-language interface over financial operations data. A user asks a question in React; FastAPI gives a language model the live dataset catalog and asks for a constrained query plan; the backend validates that plan and executes it in DuckDB; only the computed evidence is then sent to the model for explanation. The UI shows both the answer and its source rows.

The central design rule is:

> The model may interpret and explain. It may not invent datasets, columns, records, or financial calculations.

This is intentionally a **hackathon-ready grounded prototype**, not yet a production financial platform. It optimizes for accuracy, explainability, lightweight deployment and rapid adaptation when TBX supplies the official files.

## 2. Architectural goals and non-goals

### Goals

1. Ground every numeric answer in uploaded data.
2. Keep calculations deterministic and testable.
3. Prevent the model from emitting arbitrary SQL.
4. Show evidence with every successful answer.
5. Support unknown CSV schemas without redesigning the application.
6. Keep the model provider replaceable for the model-efficiency evaluation.
7. Run locally with no model credits through a narrow mock mode.

### Non-goals in the current problem scope

- Live ERP or banking integrations
- Payment execution
- Multi-tenant authorization
- Full accounting semantics
- Arbitrary analytical SQL
- Production-scale ingestion and data governance

## 3. System context

```mermaid
flowchart LR
    User[Finance user] --> UI[React chat]
    UI --> API[FastAPI API]
    API --> Model[Model provider]
    API --> Engine[Grounded query engine]
    Engine --> CSV[TBX CSV datasets]
    API --> Export[CSV export store]
```

Only FastAPI is externally addressed by the UI. The model cannot access files or DuckDB directly. It receives metadata during planning and bounded result evidence during explanation.

## 4. Container and runtime view

```mermaid
flowchart TD
    Browser[Browser :5173] --> Web[Vite React container]
    Web --> API[FastAPI container :8000]
    API --> Data[Mounted data directory]
    API --> Provider[Sarvam or mock provider]
    DB[PostgreSQL container :5432]
```

`compose.yaml` currently launches three services:

| Service | Present responsibility | Important note |
|---|---|---|
| `web` | Vite development server and React UI | Development server, not a production static build |
| `api` | Public endpoints, orchestration and DuckDB execution | Reload mode is enabled for development |
| `db` | PostgreSQL 16 | Provisioned for future persistence but currently unused |

The repository's `data/` directory is mounted at `/app/data`. `.env` selects `data/sample` today. On hack day, setting `DATA_DIRECTORY=data/uploads` isolates official files from synthetic ones.

## 5. Source-code responsibilities

```text
frontend/src/main.tsx              UI state, upload, chat and evidence rendering
backend/app/main.py                FastAPI bootstrapping and CORS
backend/app/api/routes.py          HTTP boundary and dependency construction
backend/app/assistant/service.py   Two-stage grounded orchestration
backend/app/providers/             Replaceable language-model boundary
backend/app/data/catalog.py        CSV discovery and schema introspection
backend/app/data/query_engine.py   Query validation, SQL construction and execution
backend/app/data/exports.py        Temporary CSV export cache
backend/app/schemas.py             API and internal contract models
backend/app/tools/registry.py      Future deterministic tool extension point
data/sample/                       Synthetic TBX-shaped development data
```

## 6. End-to-end chat flow

```mermaid
sequenceDiagram
    participant U as User
    participant R as React
    participant A as FastAPI
    participant L as LLM provider
    participant D as DuckDB
    U->>R: Ask finance question
    R->>A: POST /api/v1/chat
    A->>D: Discover datasets and columns
    A->>L: Question + history + catalog
    L-->>A: JSON QueryPlan
    A->>A: Pydantic and allowlist validation
    A->>D: Parameterized deterministic query
    D-->>A: Computed rows
    A->>L: Question + computed evidence
    L-->>A: Plain-language explanation
    A-->>R: Answer + confidence + evidence
    R-->>U: Answer, table and CSV link
```

### Stage A - request construction

`frontend/src/main.tsx` sends the new message and prior conversation. For assistant messages that had evidence, it includes a compact grounded context containing the dataset, calculation summary and up to ten prior rows. This is how follow-up questions can retain context without server-side session storage.

Tradeoff: this is simple and stateless, but the browser becomes responsible for conversation integrity and request size grows with history. It also means evidence included in history is sent to the external model.

### Stage B - live schema discovery

`DatasetCatalog.describe()` creates an in-memory DuckDB connection, registers every CSV in the selected directory as a view, and runs `DESCRIBE` on each view. Filenames and column names are normalized.

Why this approach:

- The official TBX schema is not yet available.
- DuckDB reads CSV directly and infers common types.
- The planner sees only datasets and columns that actually exist.
- No database migration is required for initial files.

Tradeoff: schema inference occurs repeatedly and can infer inconsistent types from imperfect files. Production ingestion should validate files once, persist a versioned catalog and reject schema drift explicitly.

### Stage C - planning

`AssistantService` creates a planner prompt containing:

- The user's question
- Up to twelve prior messages
- Today's date for relative date phrases
- The discovered dataset catalog
- The exact JSON structure the model must return

The returned object is parsed into `QueryPlan`:

```json
{
  "dataset": "vendor_payouts",
  "operation": "sum",
  "measure": "amount",
  "group_by": [],
  "filters": [
    {"column": "payout_date", "operator": "gte", "value": "2026-08-01"},
    {"column": "payout_date", "operator": "lte", "value": "2026-08-31"}
  ],
  "limit": 50
}
```

The model does not return SQL. It chooses values inside a deliberately small analytical DSL.

### Stage D - validation and SQL construction

Validation occurs at two levels:

1. Pydantic restricts operations, filter operators, grouping width and result limit.
2. `GroundedQueryEngine` checks every requested dataset and column against the live catalog.

Identifiers are accepted only after catalog validation and are quoted. Filter values are passed as query parameters. This blocks the ordinary model-to-SQL injection path and prevents arbitrary statements such as `DROP`, joins to hidden tables, or unbounded queries.

Supported operations:

- `list`
- `count`
- `sum`
- `average`
- `minimum`
- `maximum`

Supported filters:

- Equality and inequality
- Greater/less than comparisons
- Case-insensitive substring matching

Supported grouping is limited to three real columns. Results are capped at 200 by the schema, though the configured `max_result_rows` setting is not yet wired into this cap.

### Stage E - evidence generation

DuckDB returns the rows and column names. The backend builds an `Evidence` object containing:

- Dataset name
- Returned columns
- Source or aggregated rows
- Returned row count
- Human-readable calculation summary
- Temporary export identifier

The same rows are serialized into CSV and inserted into `ExportStore`.

### Stage F - grounded explanation

The provider is called a second time with only the original question and computed evidence. The explainer prompt explicitly forbids adding or recalculating numbers. This separation makes it possible to inspect whether a wrong answer came from planning, deterministic execution, or explanation.

Tradeoff: two model calls improve grounding boundaries but roughly double provider overhead and add latency. A lower-cost alternative is to generate the answer deterministically from result templates and use a model only when natural-language explanation adds value.

### Stage G - rendering and export

React renders model output as text rather than raw HTML, reducing script-injection risk. Evidence is rendered as a horizontally scrollable table. The export link calls `GET /api/v1/exports/{id}.csv`.

## 7. Provider architecture

`LLMProvider` is a Python protocol with one method:

```python
async def generate(messages: list[Message]) -> ProviderResponse
```

### Sarvam provider

`SarvamProvider` calls the configured chat-completions endpoint through `httpx`, using `api-subscription-key`. The key remains server-side. The rest of the application depends only on the neutral provider interface.

Benefits:

- Easy replacement after TBX publishes its lightweight-model guidance
- No Sarvam-specific DTOs outside one module
- Async I/O and a bounded timeout

Current limitations:

- `sarvam-105b` may not satisfy the scored lightweight-model requirement.
- No streaming, retry/backoff, circuit breaker or rate-limit handling.
- No schema-enforced structured-output API is used; JSON compliance relies on prompting and validation.
- Response-shape changes can currently surface as unhandled key errors.

### Mock provider

Mock mode is not an AI model. It is a deliberately narrow rule-based planner supporting the sample acceptance paths: payout routing, amount summation, vendor grouping, status filtering and `last month` date resolution. It proves that ingestion, deterministic calculation, evidence and export work without credits.

It must not be used for model-accuracy claims.

## 8. Why React + FastAPI + DuckDB

| Choice | Why it fits | Tradeoff |
|---|---|---|
| React + TypeScript | Fast interactive chat/table UX, familiar ecosystem | Current UI is a single component and needs decomposition as it grows |
| FastAPI | Strong Python AI/data ecosystem, async APIs, Pydantic contracts, automatic OpenAPI | Less compile-time enforcement than Java; discipline is required at boundaries |
| DuckDB | Excellent local analytical SQL over CSV with no server setup | Repeated scans and no durable catalog; not the system of record for production |
| Pydantic query DSL | Constrains the model and makes plans testable | Narrow expressiveness; complex finance questions need more operators |
| Two-pass LLM flow | Calculation happens between interpretation and explanation | More latency and token usage |
| Stateless chat history | Simple demo deployment | Client-controlled context, no durable sessions, larger requests |
| Provider protocol | Model can change without rewriting orchestration | Lowest-common-denominator interface lacks streaming and structured outputs |

### Why Spring Boot is not in the current request path

This problem is AI- and analytics-first, while authentication, multi-tenancy and transactional command execution are explicitly out of scope. Adding Spring Boot would create another deployment, contract and network boundary without improving the scored grounding path. If the project later executes payments or owns transactional workflows, Spring Boot can become the command/security service while FastAPI remains the analytical assistant.

## 9. Data strategy and replacement of sample data

The synthetic files intentionally mirror only the resource categories promised by TBX. They do not claim to mirror the final schema.

```text
data/sample/    committed synthetic data
data/uploads/   gitignored official or locally uploaded data
```

On hack day:

1. Set `DATA_DIRECTORY=data/uploads`.
2. Add or upload the official files.
3. Inspect `GET /api/v1/datasets`.
4. Compare inferred columns with the TBX data dictionary.
5. Add a normalization/semantic layer for aliases and relationships.
6. Run golden questions before changing prompts.

Changing the directory is trivial. Supporting different names is easy. Supporting different semantics is not automatically free: if TBX separates vendor IDs, payouts and reconciliation across normalized files, joins and a semantic model will be required.

## 10. Grounding and security boundaries

### What is currently protected

- The model cannot emit arbitrary SQL.
- Dataset and column identifiers must exist in the live catalog.
- Filter values are parameterized.
- Query operations and result limits are allowlisted.
- No model-generated HTML is rendered.
- `.env` and uploaded data are excluded from Git.
- Missing data returns clarification rather than a guessed answer.

### What is not yet protected

- Upload size, row count and decompression/resource limits
- Authentication and access control
- File malware scanning or CSV formula-injection neutralization on export
- Concurrent replacement of a CSV during a query
- Prompt-injection content embedded inside financial fields
- Sensitive-data minimization before sending evidence to the model
- Per-user dataset isolation
- Audit-grade lineage and immutable dataset versions

The query DSL limits the blast radius of prompt injection, but it does not guarantee semantic correctness. A model can still choose a valid but wrong column or date range.

## 11. Accuracy model

There are three independent accuracy layers:

1. **Intent accuracy:** Did the planner select the correct dataset, metric, filters and dates?
2. **Computation accuracy:** Did deterministic SQL correctly implement the plan?
3. **Explanation fidelity:** Did the final response faithfully describe the computed evidence?

Evaluation should report these separately. A useful golden test fixture stores the question, expected `QueryPlan`, expected rows and expected answer facts. This makes model comparisons meaningful and helps show why a smaller model is sufficient.

## 12. Current limitations, prioritized

### P0 - required for a credible final demo

1. **No joins.** Reconciliation, vendor and chart-of-accounts files cannot currently be combined unless fields are denormalized.
2. **No comparison plan.** “Compare with the month before” needs two periods or a time-bucket operator; the DSL supports one query only.
3. **Simplistic confidence.** Confidence is `high` whenever rows exist, even if the planner was uncertain.
4. **No planner trace in the response.** Evidence shows a calculation summary but not the full validated plan or SQL-equivalent lineage.
5. **Model choice unresolved.** The default Sarvam model is not justified against the lightweight constraint.
6. **Limited tests.** There is no golden NL-to-plan suite, date-boundary suite, empty/null data coverage, or end-to-end API test.

### P1 - important engineering improvements

1. `total_rows` means returned rows, not total matching rows before `LIMIT`.
2. The catalog reopens and rescans all CSV files multiple times per question.
3. Export data is held in one process and disappears on restart; multiple workers would have inconsistent stores.
4. Upload reads the complete file into memory and can overwrite a sanitized filename.
5. PostgreSQL and `DATABASE_URL` are unused while the API waits for the database container.
6. `ToolRegistry` and `percentage_change` are injected but not used by `AssistantService`.
7. `max_result_rows` is configured but not connected to `QueryPlan.limit`.
8. Errors from malformed provider payloads, DuckDB execution and serialization are not handled uniformly.
9. Currency aggregation has no guard against summing mixed currencies.
10. Nulls, refunds, negative payouts and duplicate transaction IDs have no explicit semantics.

### P2 - production hardening

- Durable conversation/session storage
- Background ingestion jobs
- Dataset versioning and lineage
- Metrics, tracing and structured logs
- Rate limiting and quotas
- Static frontend build behind a production web server
- Model response caching
- Horizontal-worker-safe export storage
- Secret manager integration
- Accessibility and richer loading/error states

## 13. Recommended next architecture

```mermaid
flowchart TD
    Q[Question] --> Planner[Structured planner]
    Planner --> Semantic[TBX semantic model]
    Semantic --> Validator[Policy validator]
    Validator --> Executor[DuckDB executor]
    Executor --> Lineage[Evidence and lineage]
    Lineage --> Answer[Template or lightweight explainer]
    Lineage --> Eval[Golden evaluation harness]
```

The most valuable next component is a semantic model derived from the official data dictionary. It should define canonical concepts such as `transaction amount`, `payout date`, `reconciliation status`, allowed joins, currency behavior and fiscal/calendar date rules. The planner should target those concepts rather than raw column names.

## 14. Testing strategy

### Unit tests

- Every DSL operation and filter
- Identifier rejection and parameter binding
- Date boundaries, leap years and month transitions
- Empty results, null values, decimals and negative amounts
- Currency partitioning

### Contract tests

- Each provider returns parseable plans or a clarification
- Upload/catalog response schemas remain stable
- Evidence and export contain identical rows

### Golden evaluation suite

For each representative question, store:

- Expected intent
- Expected plan
- Expected deterministic result
- Required facts in the explanation
- Whether clarification is expected
- Model tokens, latency and cost

This suite directly supports the hackathon's accuracy and model-efficiency scoring.

### End-to-end tests

- Upload files, ask a question, inspect evidence and download CSV
- Follow-up question reusing prior context
- Missing dataset and ambiguous question behavior
- Provider timeout and invalid JSON behavior

## 15. Decision summary

The current design is strong where the problem is scored most heavily: it creates a hard boundary between probabilistic interpretation and deterministic finance calculations, and it makes source rows visible. Its greatest weakness is analytical expressiveness, not framework choice. The priority on hack day should therefore be the TBX semantic model, joins/comparisons and a measured lightweight-model evaluation—not adding more infrastructure.

