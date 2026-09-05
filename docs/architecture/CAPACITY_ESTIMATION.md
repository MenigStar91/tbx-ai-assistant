# Capacity and back-of-the-envelope estimation

These are planning assumptions, not benchmark results. Replace them with TBX
telemetry before making production claims.

## Assumed workload

| Input | Demo | Department | Production candidate |
|---|---:|---:|---:|
| Accounts | 1,000 | 100,000 | 1,000,000 |
| Transactions/year | 100,000 | 10,000,000 | 100,000,000 |
| Active users | 5 | 500 | 5,000 |
| Peak questions/second | 0.2 | 10 | 100 |
| Average raw transaction row | 250 B | 250 B | 250 B |

## Storage

At 250 bytes per transaction:

- 100k rows ≈ 25 MB raw CSV.
- 10M rows ≈ 2.5 GB/year raw.
- 100M rows ≈ 25 GB/year raw.

Columnar Parquet commonly reduces scanned/storage bytes materially, but the
ratio depends on cardinality and must be measured. Retaining raw, curated and
indexes/caches suggests budgeting roughly 2–3× the compressed curated size.

## Request latency budget

| Stage | P95 target | Choice |
|---|---:|---|
| Guards and context | 20 ms | Deterministic, cached vocabulary |
| Planner model | 1,200 ms | One small-model call, ≤400 output tokens |
| Query | 700 ms | DuckDB for demo; partitioned analytical store at scale |
| Reconciliation/narration | 30 ms | Deterministic code, no second model call |
| Network/UI | 300 ms | Compact JSON and bounded evidence |
| Total | ≤2.25 s | Target, not a measured guarantee |

With 100 peak questions/second and 2.25 seconds P95, Little’s Law gives about
225 concurrent in-flight requests. The model provider is likely the bottleneck;
rate limits and observed latency should determine worker count, not CPU alone.

## Token and cost envelope

The current design makes one model call. A target envelope is 350 input + 100
output tokens per answered question. At 10,000 questions/day this is about 4.5M
tokens/day. Actual cost is `tokens × provider price`; keep pricing outside code
and record real tokens at `/api/v1/metrics`.

## Scaling decisions

| Threshold/symptom | Recommended change |
|---|---|
| CSV scan exceeds latency target | Convert validated input to partitioned Parquet |
| Dataset exceeds one-node memory/scan budget | Move semantic views to warehouse/lakehouse SQL |
| Multiple API replicas | Replace in-memory exports and local metrics with shared durable stores |
| More than one tenant | Add tenant-scoped storage, authorization and row-level policy before query planning |
| Repeated expensive questions | Cache by dataset version + validated plan, never raw user text alone |

The React/FastAPI/model contracts do not change when DuckDB is replaced; only
the deterministic catalog/executor adapter does.
