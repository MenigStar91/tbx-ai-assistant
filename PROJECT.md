# FiFi — Financial Findings

**A finance assistant that answers plain-language questions from real data, and
refuses when it cannot.**

TBX · BVP Tech Catalyst Hackathon · branch `fifi-integration`

---

## 1. The one architectural rule

> **The language model translates the question into a plan. It never sees data
> rows, and it never does arithmetic.**

The model fills a small JSON object naming a table, an operation, a measure and
some filters. SQL computes every number. The answer sentence is a Python
template filled with database values.

Nothing downstream of the planner can invent a figure, because the model is not
in that path. That is what makes "grounded" a structural property rather than a
claim about prompt wording — and it is worth 30% of the score.

```
question ─▶ guards ─▶ model ─▶ plan repair ─▶ validate ─▶ SQL ─▶ reconcile ─▶ template
            (0 tok)   (1 call)  (deterministic)            (real)   (check)     (no model)
```

**One model call per question.** There is no second call to phrase the answer —
that halves token spend and removes the last place a figure could drift.

---

## 2. What it does

| Capability | How |
|---|---|
| Natural-language questions | model emits a validated `QueryPlan`, never SQL |
| Grounded retrieval | every figure computed by SQL over the three TBX tables |
| Verifiable answers | each answer ships the rows behind it, the SQL, and a CSV export |
| Hallucination guardrails | eight refusal paths, five of them before any model call |
| Multi-turn | the previous plan is merged in Python; the transcript never enters a prompt |
| Explainability | plan corrections, token cost and latency are shown with every answer |
| Lightweight model | Qwen2.5-1.5B, local, no API key — the cap is 20B |
| Confidence signalling | high/low, driven by whether rows actually matched |

---

## 3. Respecting the schema

TBX gave three tables and two instructions: **no schema changes**, and
**SELECT-only access**. Both are honoured literally.

**No columns were added.** An earlier build derived `debit_amount`,
`credit_amount` and `reconciliation_status`. All were removed. "Spend" is now a
filter on the real `transaction_type` column, not a column we invented.

**Nothing is created in their database.** The joined, masked surface the planner
queries is not a view — it travels inside every statement as an inlined
projection:

```sql
SELECT bank_name, SUM(transaction_amount) AS result
FROM ( SELECT … joins … RIGHT(account_number,4) AS account_last4 … ) AS "transaction"
WHERE transaction_type = 'debit' GROUP BY bank_name
```

So the required grant is exactly:

```sql
GRANT SELECT ON tbx.bank, tbx.account, tbx.transaction TO 'fifi'@'%';
```

No `CREATE VIEW`, no `CREATE INDEX`, no `DROP`, no writes. Verified against a
MySQL 8 database containing only the three base tables.

**Protected fields never leave the source layer.** `account_number` and
`utr_number` are not in the projection at all — the surface exposes
`account_last4` and a boolean `utr_available`. They cannot be selected, filtered
on, or exported, because they do not exist above that line.

---

## 4. Reconciliation — the question we refuse

The problem statement's own example is *"which transactions are still
unreconciled?"* **The schema cannot answer it.** There is no matching table, no
ledger, no status column.

We built a proxy (no reference number and no UTR ⇒ unreconciled), then **deleted
it**. Modelling a status the source system never published is the exact failure
the brief calls a liability.

> *"This dataset does not contain reconciliation data. The schema covers banks,
> accounts and transactions only — there is no matching or ledger table, and no
> status field to read. I would have to invent one to answer, so I will not.
> I can tell you which transactions carry a reference number, if that helps."*

Refusing their own example question, and explaining exactly why, is a stronger
claim than any answer we could have given.

---

## 5. Making a small model work

§7 asks for the *lowest possible model with the highest possible accuracy*. The
accuracy does not come from the model — it comes from correcting the model
deterministically. **Fifteen repair rules**, each written against an observed
failure:

| Observed | Repair |
|---|---|
| `"transactions"` — table does not exist | resolve to the nearest real table |
| `account_full` with a column only `transaction` has | move the query to the table that fits |
| `dataset.date` — invented column name | strip the prefix, fuzzy-match to a real column |
| "total spend" grouped by date | drop a grouping the question never asked for |
| "how many payouts failed" → `status ≠ failed` | flip `neq` to `eq` with no negation present |
| `operation` omitted entirely | infer it from the question |
| "last month" computed as the wrong month | resolve the window in Python, anchored per column |
| "May and June" → June only | span every month named |
| `bank_code = "KOTAK"` (it is a bank *name*) | move the filter to the sibling column |
| `bank_name = "HDFC"` | canonicalise to `HDFC BANK LIMITED` |
| `"spend"` measured on `transaction_amount` | add the `transaction_type = debit` filter |
| `"spned"` — a typo | direction detection tolerates misspellings |

Every correction is returned with the answer, so a repaired plan is visible
rather than silently different.

---

## 6. Guardrails

Eight refusal paths. **Five run before the model**, so they cost zero tokens and
behave identically no matter which model is loaded.

| Guard | Catches | Cost |
|---|---|---|
| Small talk | "hii", "what data do we have" — answered, not refused | 0 |
| Too vague | "What i" — asks instead of guessing | 0 |
| Protected field | "show the full account number", any UTR lookup | 0 |
| Reconciliation | data the schema does not contain | 0 |
| Forecasting | "what will we spend next quarter" | 0 |
| Unknown entity | "Zylo Corp" — suffixes stripped, so a shared "Corp" cannot carry a match | 0 |
| Unsupported subject | "EBITDA" — with typo tolerance, so "mcuh" is a misspelling | 0 |
| Invented filter value | `bank_code = "12345"` — refuses and lists real values | 1 call |
| Failed reconciliation | breakdown does not sum to the headline — the number is withheld | 1 call |

The last one is the strongest: **if the table under a number does not add up to
it, we do not show the number.**

---

## 7. Measured results

23 questions, 9 capabilities, four backends, same question set.

| Backend | Params | Accuracy | Refusals | Tokens | Median | p95 |
|---|---|---|---|---|---|---|
| keyword baseline | 0 | 91.3% | 6/6 | 347 | 0 ms | 0 ms |
| qwen2.5:0.5b | 494M | 87.0% | 6/6 | 394 | 2,058 ms | 11,428 ms |
| **qwen2.5:1.5b** | **1.5B** | **95.7%** | **6/6** | 378 | 1,530 ms | 4,634 ms |
| qwen2.5:3b | 3B | 82.6% | 6/6 | 385 | 4,200 ms | 8,832 ms |

**Three findings worth saying out loud:**

1. **Refusals are 6/6 on every backend, including zero parameters.** They run
   before the model, so grounding does not depend on model choice.
2. **Bigger is not better.** 3B scores *lower* than 1.5B and takes 2.7× the
   latency. We shipped the smallest model that cleared the bar, and this table
   is the justification.
3. **A no-model keyword router reaches 91.3%.** The 1.5B earns its place by 4.4
   points, mostly filtering and breakdowns. It buys language flexibility, not
   arithmetic.

Weakest capability is **breakdown (33–67% across all backends)** — the clearest
thing to improve next.

---

## 8. How it is built

```
backend/app/
  assistant/
    guards.py        refusals, entity resolution, typo tolerance, vocabulary
    repair.py        15 deterministic plan corrections, period resolution
    followups.py     multi-turn as a plan merge — narrow, widen, re-narrow
    narrate.py       templated answers + the number-fidelity tripwire
    smalltalk.py     greetings, "what data do we have", vague questions
    service.py       orchestration
  data/
    projections.py   the safe surface, defined once, inlined per query
    mysql_source.py  read-only MySQL catalog
    catalog.py       file/DuckDB catalog for local work
    query_engine.py  plan → parameterised SQL → result + reconciliation check
    dialect.py       MySQL portability rules
  providers/         keyword | ollama/openai-compatible | sarvam, with fallback
evals/               23 questions with independent-SQL expectations + scorer
scripts/             MySQL setup, portability verifier, data generator
```

**3,847 lines of source, 902 lines of tests, 92 tests passing.**

Switching data source is one environment variable:

```bash
DATA_BACKEND=files   DATA_DIRECTORY=data/tbx     # local, DuckDB over files
DATA_BACKEND=mysql   MYSQL_HOST=… MYSQL_USER=…   # TBX, SELECT-only
```

Nothing downstream knows which engine it is on. The same generated SQL runs on
both and returns identical figures — asserted by
`backend/tests/test_sql_portability.py`.

---

## 9. Honest limitations

- **Ten rows.** Every figure quoted here comes from TBX's sample data. Correct,
  but small — aggregation paths are not stress-tested.
- **20M rows will need work.** Connections are per-request (no pooling), and the
  vocabulary builder runs `COUNT(DISTINCT)` per text column at first boot. Both
  are known, neither is hard.
- **Breakdowns are the weak capability**, 33–67% depending on backend.
- **Vendor questions are unanswerable.** There is no vendor table; counterparty
  names live inside free-text `description`. Parsing them is the obvious next
  feature.
- **Single eval run per backend.** Small models vary; treat ±1 question as noise.

---

## 10. Running it

```bash
ollama serve && export OLLAMA_KEEP_ALIVE=30m
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev            # http://localhost:5173
```

```bash
cd backend && ../.venv/bin/python -m pytest tests -q        # 92 passed
.venv/bin/python evals/run.py --provider openai             # accuracy by capability
scripts/verify_mysql.sh tbx fifi fifi                       # MySQL portability
```

The six-question demo sequence, with expected answers, is in **`DEMO.md`**.
