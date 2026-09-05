"""Keeping the generated SQL runnable on both DuckDB and MySQL.

The prototype queries DuckDB over files; the real dataset is a MySQL database.
Rather than maintain two query builders, the SQL is written in the portable
intersection of the two dialects and the few remaining differences are handled
here.

Portable by construction (verified on both engines):
  CAST(x AS CHAR)                 - MySQL rejects CAST(x AS VARCHAR)
  ORDER BY (c IS NULL), c DESC    - MySQL has no NULLS LAST
  LOWER(), TRIM(), LENGTH(), RIGHT(), COUNT/SUM/AVG/MIN/MAX, LIMIT

Handled below:
  identifier quoting   - MySQL treats "x" as a string literal unless the session
                         runs in ANSI_QUOTES mode, so we switch the session on
                         connect instead of quoting differently everywhere
  parameter markers    - DuckDB takes ?, MySQL drivers take %s
"""

from __future__ import annotations

import re

# Run once per MySQL connection. With ANSI_QUOTES the double-quoted identifiers
# this codebase emits are read as identifiers, exactly as DuckDB reads them, so
# no SQL has to change shape between engines.
MYSQL_SESSION_SETUP = (
    "SET SESSION sql_mode = CONCAT(@@sql_mode, ',ANSI_QUOTES')",
)

# DuckDB-only constructs. Asserted against in the tests so a future change
# cannot quietly reintroduce something MySQL will reject.
NON_PORTABLE = (
    re.compile(r"\bAS\s+VARCHAR\b", re.IGNORECASE),
    re.compile(r"\bNULLS\s+(FIRST|LAST)\b", re.IGNORECASE),
    re.compile(r"\bread_csv_auto\b", re.IGNORECASE),
    re.compile(r"\bstrftime\b", re.IGNORECASE),
    re.compile(r"\bdate_trunc\b", re.IGNORECASE),
    re.compile(r"`"),
)


def portability_problems(sql: str) -> list[str]:
    """Constructs in `sql` that MySQL will not accept."""
    return [pattern.pattern for pattern in NON_PORTABLE if pattern.search(sql or "")]


def to_driver_params(sql: str, marker: str = "%s") -> str:
    """Rewrite ? placeholders for drivers that use a different marker.

    Only bare markers are rewritten; a ? inside a quoted string is left alone.
    """
    out, in_single, in_double = [], False, False
    for char in sql:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        if char == "?" and not in_single and not in_double:
            out.append(marker)
        else:
            out.append(char)
    return "".join(out)
