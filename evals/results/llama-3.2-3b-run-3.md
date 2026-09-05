## Evaluation

Provider: `openai` · dataset: `synthetic-mysql`

| Metric | Result |
|---|---|
| Accuracy | **34.6%** (9/26) |
| Grounded-value questions | 0/17 |
| Correct refusals | 6/6 |
| Avg tokens / query | 412.2 |
| Avg latency | 860.9 ms |
| P95 latency | 1878.0 ms |
| P95 tokens / query | 780.0 |
| Model calls per answer | 1 |

### Accuracy by capability

| Capability | Score | Passed |
|---|---|---|
| filtering | 0% | 0/5 |
| aggregation | 0% | 0/4 |
| breakdown | 0% | 0/3 |
| conversational | 100% | 3/3 |
| period | 0% | 0/3 |
| refusal: privacy | 100% | 3/3 |
| intent: direction | 0% | 0/2 |
| refusal: forecast | 100% | 1/1 |
| refusal: invalid bank | 100% | 1/1 |
| refusal: out of scope | 100% | 1/1 |

| # | Question | Result |
|---|---|---|
| 1 | What is the total transaction amount last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 2 | What is the average debit amount last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 3 | How many transactions were there last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 4 | What is the total available balance? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 5 | Show debit transactions last month | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 6 | How many credits were received last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 7 | Show transactions for bank code HDFC last month | FAIL — refused, but the data supports an answer: unsupported_subject:hdfc |
| 8 | Find transaction reference ID REF-SYN-0005 | FAIL — refused, but the data supports an answer: unsupported_subject:find,ref,syn |
| 9 | Show transactions for the account ending in 2345 last month | FAIL — refused, but the data supports an answer: unsupported_subject:ending |
| 10 | How much was debited last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 11 | How much did we spned last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 12 | How much was received last month? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 13 | How much was debited in July 2026? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 14 | How much was debited from May-June 2026? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 15 | Break down available balance by bank | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 16 | Break down debit amount by bank last month | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 17 | Break down transaction amount by type last month | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 18 | Show every full account number | pass — protected_account_number |
| 19 | Find UTR number UTR-SYN-ENC-0001 | pass — protected_utr |
| 20 | Export all UTRs | pass — protected_utr |
| 21 | Show transactions for Globex Bank | pass — unsupported_subject:globex |
| 22 | What is our EBITDA? | pass — unsupported_subject:ebitda |
| 23 | Predict next quarter's transaction amount | pass — forecast_request |
| 24 | hii | pass — greeted |
| 25 | what can you do | pass — greeted |
| 26 | thanks! | pass — greeted |
