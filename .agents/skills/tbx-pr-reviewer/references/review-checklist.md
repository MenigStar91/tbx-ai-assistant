# TBX Review Checklist

Use the relevant sections; do not force every item onto unrelated changes.

## Grounding and query safety

- A model cannot supply raw SQL or bypass the `QueryPlan` boundary.
- Dataset, measure, filter and grouping identifiers are checked against the live catalog.
- Filter values use parameters, not interpolation.
- Result limits cannot be bypassed.
- Empty, malformed or ambiguous plans fail closed with a clarification.
- Evidence comes from the same executed result used to form the answer and export.

## Financial correctness

- Date phrases have explicit inclusive/exclusive boundaries and timezone/calendar assumptions.
- Month-over-month logic handles January, leap years and partial periods.
- Mixed currencies are separated or normalized using an explicit rate and date.
- Refunds, reversals, negative amounts, nulls and duplicates have defined behavior.
- Reconciliation status uses the authoritative field and does not confuse pending with unreconciled.
- Aggregations and joins cannot duplicate amounts through one-to-many relationships.
- Decimal arithmetic is preserved through query, serialization and display.

## Model behavior and efficiency

- Planner output is structurally validated; explanation cannot silently replace evidence.
- Prompt changes are covered by golden question-to-plan cases.
- Model choice, calls per question, tokens, latency and fallback behavior remain measurable.
- Mock mode stays deterministic and is not presented as AI accuracy.
- Provider failures, invalid JSON, timeouts and rate limits have explicit user-safe behavior.

## Data ingestion and privacy

- Official TBX data and user exports remain ignored by Git.
- Upload type, size, row count, filename collision and schema drift are handled.
- Data sent to an external model is minimized and contains no unnecessary rows or fields.
- Concurrent upload/query behavior cannot produce a partially replaced dataset.
- CSV exports neutralize formula-leading values when opened in spreadsheet applications.

## API and multi-turn behavior

- Request/response changes remain compatible with React and documented examples.
- Follow-ups retain the intended dataset, filters and period without trusting arbitrary client history.
- Session identifiers and evidence identifiers are stable where the feature requires them.
- Errors distinguish clarification, unavailable provider, invalid dataset and internal failure.

## UI and evidence

- Every numeric answer exposes a breakdown or source rows.
- Confidence reflects intent/data certainty rather than merely non-empty results.
- Large tables, long values, nulls, dates and decimals render readably.
- Loading, empty, error and export-expired states are visible.
- Model output is not rendered as unsafe HTML.

## Tests expected by change type

| Change | Minimum useful verification |
|---|---|
| Query DSL or SQL builder | Success, rejected identifiers, parameters and boundaries |
| Date interpretation | Month/year boundary and leap-year cases |
| Dataset ingestion | Valid, malformed, empty, oversized and schema-drift cases as applicable |
| Provider or prompt | Valid plan, invalid JSON, timeout and golden intent cases |
| Evidence/export | API result and exported rows agree exactly |
| React contract | Successful answer plus loading, clarification and provider-error states |

