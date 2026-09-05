---
name: tbx-pr-reviewer
description: Review and, when explicitly requested, fix pull requests or merge requests for the TBX Finance Assistant. Use for PR/MR review, change requests, regression analysis, or preparing scoped fixes; do not use for automatic merging.
---

# TBX PR Reviewer

Review changes against the repository's actual architecture and the TBX grounding requirements. Treat GitHub pull requests and GitLab-style “MR” wording equivalently, while using the repository provider available to the user.

Before reviewing, read `docs/ARCHITECTURE.md`, the changed files, and tests covering the affected behavior. Read [references/review-checklist.md](references/review-checklist.md) when the change touches assistant orchestration, model providers, datasets, queries, evidence, exports, or the UI's grounded-answer flow.

## Select the mode

- **Review mode is the default.** Inspect and report; do not modify files, submit reviews, post comments, approve, or merge unless the user asks for that external action.
- **Fix mode requires an explicit request to change or fix the PR/MR.** Apply only changes needed to resolve verified findings. Work on the PR/MR source branch when authorized; otherwise create a separate fix branch or provide a patch.
- Never merge automatically. Never push directly to the default branch as part of reviewing a PR/MR.

## Review workflow

1. Resolve the exact repository and PR/MR. Inspect its metadata, base/head branches, diff, existing discussion, and checks when available.
2. Establish intended behavior from the request, issue, description, tests, architecture document, and surrounding code. Do not infer a defect from stylistic preference.
3. Trace changed behavior across boundaries: React request, FastAPI contract, planner, validation, deterministic execution, evidence, explanation, and export as applicable.
4. Run the smallest relevant verification first, then broader tests when justified. Distinguish failures caused by the change from unavailable infrastructure or pre-existing failures.
5. Report only actionable findings. Each finding must state severity, file/location, observable failure, triggering conditions, and a concrete correction.
6. If no material issue is found, say so and list verification performed plus residual risks or untested paths.

## Severity

- **P0:** Financial inaccuracy, fabricated/ungrounded answer, data exposure, arbitrary query/code execution, destructive behavior, or a broken primary demo path.
- **P1:** Likely functional regression, incorrect date/currency/status semantics, missing evidence, significant reliability issue, or violation of a stated requirement.
- **P2:** Maintainability, performance, observability, or test weakness with a concrete future cost.

Do not inflate style preferences into findings. Avoid duplicate findings that share one root cause.

## Fix workflow

1. Confirm the source branch is writable and current before editing.
2. Preserve unrelated user changes and the PR/MR's intended scope.
3. Add or update a test that fails for the verified defect when practical.
4. Implement the narrowest complete fix. Preserve the model/calculation trust boundary.
5. Run relevant tests and inspect the final diff for secrets, official TBX data, generated artifacts, and unrelated edits.
6. Commit with a focused message and report the commit, verification, and remaining limitations. Request separate authorization before posting a review, changing labels, approving, or merging.

## Non-negotiable repository invariants

- The LLM may interpret intent and explain computed evidence; deterministic code must calculate financial results.
- Model output must not become unrestricted SQL, a filesystem path, or an arbitrary tool invocation.
- Dataset and column identifiers must be validated against the active catalog; values must remain parameterized.
- Every successful financial answer must carry inspectable evidence or lineage.
- Missing or ambiguous data must produce clarification, not a plausible number.
- Do not commit `.env`, credentials, official TBX datasets, user financial data, or exported results.
- Do not claim mock-mode behavior as model accuracy.

## Output format

Lead with findings ordered P0, P1, then P2. Keep summaries secondary.

For each finding use:

```text
[P1] Short defect title - path:line
Failure: What becomes wrong or unsafe.
Trigger: The concrete input/state that exposes it.
Fix: The smallest appropriate correction.
```

Finish with verification performed, residual risks or untested areas, and the fix commit/branch only in fix mode.

