# Evaluation status

## Release decision

FiFi is the active implementation. **Qwen 2.5 1.5B is the current demo model**:
the FiFi in-process diagnostic scored it at 95.7% with 6/6 correct refusals,
ahead of the other locally measured Qwen sizes. It is the smallest measured
model that cleared the 95% accuracy gate. That run is preliminary because its
4,634 ms P95 latency missed the 2.5 second target and it did not traverse the
deployed HTTP boundary.

Sarvam 105B and Llama 3.2 3B remain comparison candidates. A final production
claim requires all three to be rerun through the HTTP gate below.

| FiFi diagnostic candidate | Accuracy | Refusals | Average tokens | Median latency | P95 latency |
|---|---:|---:|---:|---:|---:|
| Qwen 2.5 0.5B | 87.0% | 6/6 | 394 | 2,058 ms | 11,428 ms |
| **Qwen 2.5 1.5B** | **95.7%** | **6/6** | **378** | **1,530 ms** | **4,634 ms** |
| Qwen 2.5 3B | 82.6% | 6/6 | 385 | 4,200 ms | 8,832 ms |

## Withdrawn comparison

Three runs per model were previously recorded on the pre-FiFi `main` branch.
Every supported data question failed with `plan_validation_failed`, giving all
three candidates the same 34.6% overall score and 0/17 grounded answers. Those
runs measured a shared integration failure, not model quality, and must not be
used to name a winner.

| Candidate | Runs | Accuracy | Grounded | Refusals | Median P95 latency | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Qwen 2.5 1.5B | 3 | 34.6% | 0/17 | 6/6 | 1,087 ms | Invalid comparison; failed fastest |
| Llama 3.2 3B | 3 | 34.6% | 0/17 | 6/6 | 2,023 ms | Invalid comparison |
| Sarvam 105B | 3 | 34.6% | 0/17 | 6/6 | 1,638 ms | Invalid comparison |

The exact retired code and result files remain recoverable from branch
`archive/main-before-fifi-20260905` at commit `ce3e152`.

## Current release gate

The source of truth is `evals/http_questions.json`. `evals/run_http.py` invokes
the running application exclusively through `curl` and checks the returned
query plan, evidence value, refusals, number verification, tokens and end-to-end
latency. Run each real model three times; never enable mock fallback during a
scored run.

```bash
python evals/run_http.py \
  --model-label qwen2.5-1.5b \
  --json-output evals/results/qwen2.5-1.5b-run-1.json \
  --md-output evals/results/qwen2.5-1.5b-run-1.md

python evals/compare_http.py evals/results/*.json \
  > evals/results/model-comparison.md
```

No post-FiFi result is committed yet because it must be captured against a live
API with the intended provider and credentials. The required gate is at least
95% grounded accuracy, 100% privacy refusals, no mock fallback, and P95 latency
at or below 2.5 seconds. Update this file and the model scorecard with the
reproducible reports after the runs complete.
