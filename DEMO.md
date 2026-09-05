# FiFi — demo script

Every question below was run against the live `/api/v1/chat` on the TBX schema
(`DATA_DIRECTORY=data/tbx`, `qwen2.5:1.5b`). The figures are the real answers —
if a screenshot shows something different, something regressed.

## Before you start

```bash
ollama serve                                     # model must be warm
export OLLAMA_KEEP_ALIVE=30m                     # stops a cold-load pause mid-demo
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev                       # http://localhost:5173
```

Check nothing else owns port 8000 — the other project uses it too:
`ss -lptn 'sport = :8000'`

Ask one throwaway question before the audience arrives, so the model is loaded
and the first real answer is fast.

---

## The six-question demo (~3 minutes)

Each question proves a different scored criterion. Run them in this order.

### 1 · Grounding — 30% of the score
> **How much did we spend in total?**

```
The total of transaction_amount is 249806.00, computed over 8 records
in transaction (transaction_type eq debit).
```

**Do:** open *Verifiable breakdown*, show the SQL and the rows.
**Say:** "The model chose the query. SQL computed the number. The sentence is a
template filled with database values — the model never sees a row and never does
arithmetic."

### 2 · The refusal — the one that wins
> **How much did we pay Zylo Corp?**

```
"Zylo Corp" does not appear anywhere in the loaded data, so I cannot answer
that. Returning a figure that ignores it would be misleading.
```

**Say:** "There is no such counterparty. It refuses by name rather than
returning a total that silently ignores the filter. Company suffixes are
stripped before matching, so 'Zylo Corp' cannot ride in on the 'Corp' it shares
with a real name."

### 3 · Refusing what the schema cannot support
> **Which transactions are unreconciled?**

```
This dataset does not contain reconciliation data. The schema covers banks,
accounts and transactions only - there is no matching or ledger table, and no
status field to read. I would have to invent one to answer, so I will not.
```

**Say:** "This is the problem statement's own example question. The schema they
gave us has no reconciliation table. We could model a proxy from missing
reference numbers — we deliberately don't. Answering would mean returning
something the source system never said."

### 4 · Verifiable aggregation
> **Break down spend by bank**

```
3 groups of transaction by bank_name, across 8 records (transaction_type eq debit).
Largest: HDFC BANK LIMITED (240455.00), ICICI BANK LIMITED (9241.00),
STATE BANK OF INDIA (110.00).
```

**Do:** point at the reconciliation note under the table — the parts are
re-aggregated and compared to the headline.
**Say:** "If the table did not sum to the number above it, we would not show the
number at all."

### 5 · Multi-turn, and a real typo
Type these three in sequence, **badly on purpose**:

> **How mcuh did we spned at HDFC?**
```
The total of transaction_amount is 240455.00, computed over 6 records
in transaction (bank_code eq HDFC; transaction_type eq debit).
```

> **And at Kotak?**
```
None (transaction_type eq debit; bank_name eq KOTAK MAHINDRA BANK LIMITED).
There is 1 transaction matching everything else, but it is a credit, not a debit.
```

> **And total spent?**
```
The total of transaction_amount is 249806.00, computed over 8 records
in transaction (transaction_type eq debit).
```

**Do:** point at *Carried over:* on turn two, and the *widened: dropped bank_code*
repair on turn three.
**Say:** "Two typos, and it still resolves 'spned' to spending. The follow-up
narrows, then widens — and the context is carried by merging the previous query
plan in code, not by replaying the conversation to the model. So the prompt does
not grow, and the model never has to work out what 'that' referred to."

The Kotak answer is the best moment here: **zero is the correct answer**, and it
explains why rather than showing a bare 0.00.

### 6 · Model efficiency — 20% of the score
> **Show the metrics endpoint:** `http://localhost:8000/api/v1/metrics`

**Say:** "A 1.5-billion-parameter model, running locally, no API key, no
credits. The cap is 20B. Most of the accuracy comes from deterministic repair of
the plan the model produces, not from model size."

---

## Backup questions (all verified)

| Question | Answer |
|---|---|
| How much did we receive? | 296,810.00 over 2 records (credit) |
| How many transactions were debits? | 8 |
| What is the total available balance? | −81,229,672.84 over 10 accounts |
| Show me all transactions over 50000 | 4 matching rows |
| How much did we spend at HDFC? | 240,455.00 over 6 records |
| And in June 2026? *(follow-up)* | 169,299.00 over 4 records |

More refusals, if they push:

| Question | Behaviour |
|---|---|
| What is our EBITDA? | refuses — not in the data |
| Show me the full account number | refuses — protected, offers last four |
| What will we spend next quarter? | refuses — retrieval only, no forecasting |
| How much did we spend at Barclays? | refuses by name |
| hii | greets, and lists what you can ask |
| What data do we have? | lists the three tables and their columns |

---

## Do not demo these

- **"Which bank did we spend the most with?"** — the planner mis-handles it and
  refuses on an invented `account_id`. Use *"Break down spend by bank"* instead.
- **"How many transactions are there per bank?"** — returns a row listing rather
  than a grouped count.
- Anything about vendors or counterparties by name — the schema has no vendor
  table, and vendor names live inside free-text descriptions we do not parse yet.

---

## If someone asks

**"How do we know it isn't making numbers up?"**
Every figure comes from SQL over the three tables. The model only emits a small
JSON query plan. There is also a check that every numeral in the answer is one
we computed — a tripwire for the day anyone adds a generative rewrite step.

**"Why such a small model?"**
The brief caps the model at 20B and says defaulting to the largest available
model without justification will be scored down. We measured a ladder — a
zero-parameter keyword router, 0.5B, 1.5B, 3B — and shipped the smallest that
cleared the bar. The 0.5B scored *below* the no-model baseline; that is in the
report.

**"What happens with the real 20M-row database?"**
The three tables are read as they are. Nothing is written, no columns are added,
and the generated SQL is tested for MySQL portability
(`backend/tests/test_sql_portability.py`, `scripts/verify_mysql.sh`).

**"Did you change the schema?"**
No. Three tables, no added columns. `account_number` and `utr_number` never
leave the source layer — the query surface exposes the last four digits and a
flag for whether a UTR exists.
