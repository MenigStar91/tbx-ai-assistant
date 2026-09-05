# Final TBX data model

## Source hierarchy

```mermaid
erDiagram
    BANK ||--o{ ACCOUNT : serves
    ACCOUNT ||--o{ TRANSACTION : records
    BANK {
        varchar bank_code PK
        varchar bank_name
    }
    ACCOUNT {
        uuid account_id PK
        uuid entity_id
        varchar account_number sensitive
        int program_id
        decimal available_balance
        varchar bank_code FK
    }
    TRANSACTION {
        uuid transaction_id PK
        uuid account_id FK
        timestamp transaction_date
        enum transaction_type
        decimal transaction_amount
        varchar transaction_reference_id
        varchar utr_number protected
    }
```

## Assistant-safe contract

Raw CSVs are private `_source_*` views. The planner sees only:

| View | Added/changed fields | Protection |
|---|---|---|
| `bank` | Source bank fields | Names/codes must come from data |
| `account` | `bank_name`, `account_last4` | Full account number removed |
| `transaction` | Entity, bank, program and account-last4 from fixed joins | UTR removed; only `utr_available` exposed |

The LLM selects one safe view. It does not construct joins. This prevents
join fan-out, keeps prompts smaller and makes relationship changes local to
`DatasetCatalog._create_tbx_views()`.

## Supported complex intents

- Debit/credit totals by bank, entity, program or period
- Account balances grouped by bank, entity or program
- Transactions for a bank or account last-four
- Search by `transaction_reference_id`
- Evidence export using the exact rows that produced the response

## Known missing concepts

| Question | Missing data or permission |
|---|---|
| Vendor spend | Vendor master plus transaction-to-vendor mapping |
| Double-entry balance | Immutable debit/credit journal lines and posting status |
| Balance as of a historical time | Balance snapshots or complete ledger movements |
| Cross-currency total | Currency per amount plus approved dated FX rates |
| User-authorized scope | Identity, roles and account/entity entitlements |

Absent concepts must trigger clarification. They must not be approximated from
descriptions or guessed from bank names.
