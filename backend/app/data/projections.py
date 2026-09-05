"""The safe query surface, defined once, usable without any write privilege.

TBX grants SELECT only: no CREATE VIEW, no CREATE INDEX, nothing that alters
their schema. So the joined, masked surface the planner queries cannot be a
view in their database - it has to travel with the query.

These projections are used two ways from the same string:

    owned database   CREATE VIEW "transaction" AS <projection>
    read-only        SELECT ... FROM ( <projection> ) AS "transaction" WHERE ...

Both forms run identically on DuckDB and MySQL 8 (with ANSI_QUOTES), so there
is one definition of the surface and one set of numbers.

Constraints honoured here:
  * three tables, no extra columns beyond the join and the masking TBX asked for
  * account_number and utr_number never leave this layer
  * nothing is created, dropped or written
"""

from __future__ import annotations

# {p} is the prefix the raw tables are registered under ("_source_", "source_",
# or "" when reading a database directly).
ACCOUNT = """
SELECT CAST(a.account_id AS CHAR) AS account_id,
       CAST(a.entity_id AS CHAR) AS entity_id,
       RIGHT(CAST(a.account_number AS CHAR), 4) AS account_last4,
       a.program_id,
       a.available_balance,
       CAST(a.bank_code AS CHAR) AS bank_code,
       CAST(b.bank_name AS CHAR) AS bank_name
FROM "{p}account" a
LEFT JOIN "{p}bank" b ON b.bank_code = a.bank_code
"""

TRANSACTION = """
SELECT CAST(t.transaction_id AS CHAR) AS transaction_id,
       CAST(t.account_id AS CHAR) AS account_id,
       CAST(a.entity_id AS CHAR) AS entity_id,
       CAST(a.bank_code AS CHAR) AS bank_code,
       CAST(b.bank_name AS CHAR) AS bank_name,
       a.program_id,
       RIGHT(CAST(a.account_number AS CHAR), 4) AS account_last4,
       t.transaction_date,
       CAST(t.transaction_type AS CHAR) AS transaction_type,
       CAST(t.description AS CHAR) AS description,
       t.transaction_amount,
       CAST(t.transaction_reference_id AS CHAR) AS transaction_reference_id,
       (t.utr_number IS NOT NULL AND LENGTH(TRIM(CAST(t.utr_number AS CHAR))) > 0)
           AS utr_available
FROM "{p}transaction" t
LEFT JOIN "{p}account" a ON a.account_id = t.account_id
LEFT JOIN "{p}bank" b ON b.bank_code = a.bank_code
"""

BANK = """
SELECT CAST(bank_code AS CHAR) AS bank_code,
       CAST(bank_name AS CHAR) AS bank_name
FROM "{p}bank"
"""

PROJECTIONS: dict[str, str] = {
    "bank": BANK,
    "account": ACCOUNT,
    "transaction": TRANSACTION,
}


def projection_sql(dataset: str, prefix: str = "") -> str | None:
    """The SELECT that defines `dataset`, or None if it is a plain table."""
    template = PROJECTIONS.get(dataset)
    return template.format(p=prefix).strip() if template else None


def from_clause(dataset: str, prefix: str = "", inline: bool = False) -> str:
    """What follows FROM.

    Inlined when we may not create anything in the database we are reading.
    """
    if inline:
        projection = projection_sql(dataset, prefix)
        if projection:
            return f'( {projection} ) AS "{dataset}"'
    return f'"{dataset}"'
