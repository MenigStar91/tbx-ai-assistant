## Evaluation

Provider: `openai` · dataset: `data/sample`

| Metric | Result |
|---|---|
| Accuracy | **100.0%** (14/14) |
| Grounded-value questions | 6/6 |
| Correct refusals | 8/8 |
| Avg tokens / query | 257.9 |
| Avg latency | 343.8 ms |
| Model calls per answer | 1 |

| # | Question | Result |
|---|---|---|
| 1 | How much did we spend on vendor payouts last month? | pass — 958750 |
| 2 | Which transactions are unreconciled? | pass — 2 |
| 3 | What is the total transaction amount? | pass — 1.44075e+06 |
| 4 | How many vendor payouts are there? | pass — 11 |
| 5 | Break down spend by vendor | pass — 6 |
| 6 | What is the average transaction amount? | pass — 120062 |
| 7 | What is our EBITDA? | pass — unsupported_subject:ebitda |
| 8 | How much did we pay Globex Corporation last month? | pass — unsupported_subject:globex,corporation |
| 9 | What will our spend be next quarter? | pass — forecast_request |
| 10 | How many employees do we have? | pass — unsupported_subject:employees |
| 11 | How many support tickets were raised? | pass — unsupported_subject:support,tickets,raised |
| 12 | What exchange rate did we use? | pass — unsupported_subject:exchange,rate,use |
| 13 | Which vendor gave the best discount? | pass — unsupported_subject:best,discount |
| 14 | How much tax did we deduct at source? | pass — unsupported_subject:tax,deduct,source |
