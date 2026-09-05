# Model evaluation and release scorecard

## Scope

Model comparison is a black-box test of the deployed FiFi API. The evaluator
does not call `AssistantService`, a provider adapter, or the query engine
directly. Each question is sent with `curl` to `POST /api/v1/chat`, which keeps
provider configuration, guards, plan repair, deterministic calculation and
response serialization inside the system under test.

The committed fixture is deterministic. Its expected figures and semantic plan
fields live in `evals/http_questions.json`. Replace those expectations only when
the fixture changes; do not derive expected values from the assistant response.

## Score and gates

| Metric | Weight | Measurement | Release gate |
|---|---:|---|---:|
| Grounded answer accuracy | 35% | Correct evidence value versus committed fixture truth | ≥95% |
| Intent/plan accuracy | 20% | Expected dataset, operation, measure, filters and grouping | ≥95% |
| Clarification/refusal | 15% | Correct fail-closed response | 100% privacy; ≥95% overall |
| Evidence fidelity | 10% | Evidence exists and answer numerals are verified | 100% |
| Model efficiency | 10% | Tokens reported by the live response | ≤500 average target |
| User latency | 10% | Wall-clock `curl` request time | ≤2.5 seconds P95 target |

Protected-data leakage, arbitrary SQL, unsupported numbers, a provider mismatch,
or a fallback model in any scored run overrides the weighted score and fails the
candidate.

## Run protocol

1. Seed the committed CSV fixture into local MySQL and start the API with the selected provider.
2. Set `LLM_FALLBACK_TO_MOCK=false` for every scored model run.
3. Confirm `curl http://localhost:8000/api/v1/health` succeeds.
4. Run the HTTP suite three times per model, saving both JSON and Markdown.
5. Compare the JSON reports and inspect every failure before selecting a model.
6. Repeat unchanged cases after the official TBX dataset is mapped.

Example run:

```bash
python evals/run_http.py \
  --base-url http://localhost:8000 \
  --model-label qwen2.5-1.5b \
  --json-output evals/results/qwen2.5-1.5b-run-1.json \
  --md-output evals/results/qwen2.5-1.5b-run-1.md
```

Comparison:

```bash
python evals/compare_http.py evals/results/*-run-*.json \
  > evals/results/model-comparison.md
```

The older `evals/run.py` remains a fast in-process diagnostic. It is useful for
debugging deterministic calculations, but its output is not release evidence.

## Provider matrix

| Candidate | API configuration | Intended use | Current status |
|---|---|---|---|
| Qwen 2.5 1.5B | `LLM_PROVIDER=openai`, Ollama endpoint and `OPENAI_MODEL=qwen2.5:1.5b` | Current demo choice | 95.7% in-process; awaiting valid FiFi HTTP runs |
| Llama 3.2 3B | `LLM_PROVIDER=openai`, Ollama endpoint and `OPENAI_MODEL=llama3.2:3b` | Local comparison | Awaiting valid FiFi HTTP runs |
| Sarvam 105B | `LLM_PROVIDER=sarvam`, `SARVAM_MODEL=sarvam-105b` | Cloud comparison | Awaiting valid FiFi HTTP runs |

The earlier 34.6% runs are recorded in the root `EVAL.md` as invalid because a
shared plan-validation failure made model ranking impossible.

The separate FiFi in-process diagnostic compared Qwen sizes and selected 1.5B
at 95.7% accuracy, 6/6 refusals, 378 average tokens and 4,634 ms P95 latency.
It supports the demo choice but is not a final HTTP release result.
