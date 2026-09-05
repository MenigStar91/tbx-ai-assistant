# Model evaluation and release scorecard

## What is scored

Data distribution realism is secondary to correct intent, safe query generation
and grounded results. Use deterministic synthetic data for repeatability, then
rerun unchanged cases on the TBX dataset after access is granted.

| Metric | Weight | Calculation | Release gate |
|---|---:|---|---:|
| Answer/value accuracy | 35% | Correct value versus independent SQL | ≥95% |
| Intent/plan accuracy | 20% | Exact dataset, operation, measure, filters, grouping | ≥95% |
| Clarification/refusal | 15% | Correct fail-closed behavior | 100% for privacy; ≥95% overall |
| Evidence/export fidelity | 10% | Same rows and aggregation as answer | 100% |
| Model efficiency | 10% | Median tokens and calls per answer | 1 call; ≤500 tokens target |
| User latency | 10% | End-to-end P95 | ≤2.5 seconds target |

Final score is the weighted sum of normalized metric scores. Security failures
(protected data leakage, arbitrary SQL, unsupported number) override the score
and fail the candidate model.

## Current result status

No final-model result is claimed yet. The older 78.8% result used the retired
vendor-payout fixture and is not comparable to the final schema. The executable
source of truth is `evals/questions.json`; generate a result with:

```bash
python evals/run.py --provider openai --dataset-label local-mysql --md > EVAL.md
```

Run at least three times per candidate model and report median accuracy, tokens
and latency plus P95 latency. Label mock-provider runs as pipeline tests, never
model accuracy.

## Candidate comparison

| Candidate | Dataset | Accuracy | Refusal | Avg tokens | P95 latency | Status |
|---|---|---:|---:|---:|---:|---|
| Mock/keyword baseline | Synthetic final schema | Pending rerun | Pending | Deterministic | Pending | Plumbing only |
| Qwen 2.5 1.5B compatible endpoint | Synthetic final schema | Pending rerun | Pending | Pending | Pending | Candidate |
| Sarvam configured model | Synthetic + TBX | Pending API/data | Pending | Pending | Pending | Candidate |

Commit the generated `EVAL.md` only when the command, model identifier, dataset
version and timestamp are recorded and reproducible.
