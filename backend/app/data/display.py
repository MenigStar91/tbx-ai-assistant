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


# The TBX schema carries no reconciliation column. A transaction with nothing to
# match against is what an operations team calls unreconciled, so that is the
# definition used - and it is stated in every answer that relies on it, because
# it is derived rather than given.
RECONCILIATION_DEFINITION = (
    "This schema has no reconciliation column. A transaction is counted as "
    "unreconciled when it carries no reference number and no UTR to match "
    "against, and partially reconciled when one of the two is missing."
)
