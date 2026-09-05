# Documentation map

This directory separates product requirements, system decisions, data contracts,
operations and evaluation so hack-day changes stay local and reviewable.

## 1. Product

- [Problem statement and acceptance criteria](requirements/PROBLEM_STATEMENT.md)

## 2. Architecture

- [Architecture deep dive](ARCHITECTURE.md)
- [Capacity and back-of-the-envelope estimates](architecture/CAPACITY_ESTIMATION.md)

## 3. Data and correctness

- [Final TBX data model](data/DATA_MODEL.md)
- [Reconciliation and ingestion orchestration](data/RECONCILIATION.md)

## 4. Evaluation

- [Model scorecard and release gate](evaluation/MODEL_SCORECARD.md)
- [Executable golden questions](../evals/questions.json)
- [Black-box HTTP golden questions](../evals/http_questions.json)
- [Curl-backed HTTP evaluator](../evals/run_http.py)
- [HTTP result comparison](../evals/compare_http.py)

## 5. Repository operations

- [PR/MR reviewer skill](../.agents/skills/tbx-pr-reviewer/SKILL.md)

Update the lowest-level document first when a contract changes, then update
`ARCHITECTURE.md` and the root `README.md` only when their overview is affected.
