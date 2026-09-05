# Product requirement: grounded financial assistant

## Objective

TBX builds technology that helps banks and businesses manage connected financial
operations. The proof of concept must let a financial manager ask ordinary
questions in natural language and receive fast, useful answers calculated from
the available data—not figures composed by a language model.

## Required behavior

1. Understand finance questions and relevant conversational context.
2. Generate a constrained query plan; never accept model-generated SQL.
3. Execute calculations and joins deterministically against the loaded data.
4. Return the answer with inspectable evidence and an export.
5. Say when the question is ambiguous or unsupported.
6. State which dataset, fields or user permission would make it answerable.
7. Keep the chat concise, friendly, token-efficient and responsive.
8. Provide setup instructions, architecture, sample questions and model metrics.

## Acceptance examples

| User intent | Expected behavior |
|---|---|
| Debit total for last month | Resolve dates against the loaded data, filter debits and compute the sum |
| Transactions for one bank | Use the deterministic bank-account-transaction join |
| Vendor spend | Clarify that vendor master and transaction-vendor mapping are absent |
| Double-entry status | Clarify that journal lines are absent; do not infer it from bank transactions |
| Future cash position | Refuse unsupported forecasting unless an approved forecasting dataset/tool exists |
| Unknown bank | Ask for a bank present in the accessible bank master |

## Success measures

- Intent/query-plan exact match on the golden set
- Answer/value accuracy against independent SQL
- Correct refusal and clarification rate
- Evidence and export fidelity
- P50/P95 end-to-end latency
- Tokens and model calls per request
- Zero protected-field leakage

Business impact should be presented as time saved per recurring question and
adoption potential, with assumptions stated separately from measured results.
