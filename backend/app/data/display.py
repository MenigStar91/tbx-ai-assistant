"""Columns a person actually reads, per dataset.

A joined view is wide, and a row listing showing every column is unreadable.
The remaining columns stay queryable and stay in the CSV export - this only
narrows what is rendered in the evidence table.
"""

PREFERRED_DISPLAY_COLUMNS: dict[str, list[str]] = {
    "transaction": [
        "transaction_date", "transaction_type", "description", "transaction_amount",
        "reconciliation_status", "bank_name", "account_last4", "transaction_reference_id",
    ],
    "account": [
        "account_last4", "bank_name", "program_id", "available_balance", "entity_id",
    ],
}


# The published schema carries no reconciliation, matching or ledger data. We do
# not model a proxy for it: inventing a status from missing reference numbers
# would be answering with something the source system never said.
RECONCILIATION_UNAVAILABLE = (
    "This dataset does not contain reconciliation data. The schema covers banks, "
    "accounts and transactions only - there is no matching or ledger table, and no "
    "status field to read. I would have to invent one to answer, so I will not. "
    "I can tell you which transactions carry a reference number, if that helps."
)



# Columns that identify the same real-world thing. A follow-up that filters on
# one must retire a filter on any of the others: "spend at HDFC" then "and at
# Kotak?" otherwise keeps bank_code=HDFC alongside bank_name=KOTAK... and
# quietly returns zero rows for a question the data can answer.
EQUIVALENT_COLUMNS: list[set[str]] = [
    {"bank_code", "bank_name"},
    {"account_id", "account_last4", "account_number"},
]


def equivalent_to(column: str) -> set[str]:
    for group in EQUIVALENT_COLUMNS:
        if column in group:
            return group
    return {column}
