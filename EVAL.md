## Evaluation

Provider: `openai` · dataset: `data/sample`

| Metric | Result |
|---|---|
| Accuracy | **78.8%** (26/33) |
| Grounded-value questions | 13/20 |
| Correct refusals | 10/10 |
| Avg tokens / query | 379.1 |
| Avg latency | 734.7 ms |
| Model calls per answer | 1 |

### Accuracy by capability

| Capability | Score | Passed |
|---|---|---|
| refusal: out of scope | 100% | 5/5 |
| aggregation | 75% | 3/4 |
| filtering | 50% | 2/4 |
| period | 75% | 3/4 |
| breakdown | 67% | 2/3 |
| conversational | 100% | 3/3 |
| refusal: unknown entity | 100% | 3/3 |
| typo tolerance | 33% | 1/3 |
| entity resolution | 100% | 2/2 |
| refusal: forecast | 100% | 2/2 |

| # | Question | Result |
|---|---|---|
| 1 | What is the total transaction amount? | pass — 1.44075e+06 |
| 2 | How many vendor payouts are there? | pass — 11 |
| 3 | What is the average transaction amount? | pass — 120062 |
| 4 | What is the largest single transaction? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 5 | Which transactions are still unreconciled? | pass — 2 |
| 6 | How many transactions were reconciled? | FAIL — got 12.0, expected 6 |
| 7 | How many vendor payouts failed? | pass — 1 |
| 8 | Total transaction spend on payroll | FAIL — got 1440750.0, expected 184000 |
| 9 | How much did we spend on vendor payouts last month? | pass — 958750 |
| 10 | How much did we spend on vendor payouts in July 2026? | pass — 460000 |
| 11 | What was the transaction spend in 2026? | pass — 1.44075e+06 |
| 12 | What was the spend in 2019? | FAIL — refused, but the data supports an answer: plan_validation_failed |
| 13 | Break down spend by vendor | pass — 6 |
| 14 | Break down transaction spend by category | FAIL — got 0.0, expected 6 |
| 15 | Show me monthly transaction spend | pass — 1.44075e+06 |
| 16 | How much did we pay CloudScale Systems in total? | pass — 415500 |
| 17 | How much did we pay CloudScale Corp in total? | pass — 415500 |
| 18 | How mcuh did we spend on vendor payouts last month? | pass — 958750 |
| 19 | Which transactoins are still unreconciled? | FAIL — got 12.0, expected 2 |
| 20 | Totl spend by vendr | FAIL — refused, but the data supports an answer: unknown_entity:Totl |
| 21 | How much did we pay Globex Corporation last month? | pass — unknown_entity:Globex Corporation |
| 22 | How much did we pay Zylo Corp last month? | pass — unknown_entity:Zylo Corp |
| 23 | Which vendor gave the best discount? | pass — unsupported_subject:best,discount |
| 24 | What is our EBITDA? | pass — unknown_entity:EBITDA |
| 25 | How many employees do we have? | pass — unsupported_subject:employees |
| 26 | How many support tickets were raised? | pass — unsupported_subject:support,tickets,raised |
| 27 | What exchange rate did we use? | pass — unsupported_subject:exchange |
| 28 | How much tax did we deduct at source? | pass — unsupported_subject:deduct,source |
| 29 | What will our spend be next quarter? | pass — forecast_request |
| 30 | Predict our vendor payouts for next year | pass — forecast_request |
| 31 | hii | pass — greeted |
| 32 | what can you do | pass — greeted |
| 33 | thanks! | pass — greeted |
