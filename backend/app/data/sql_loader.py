"""Load MySQL-flavoured DDL and INSERTs into DuckDB.

The TBX dataset ships as SQL, not CSV: CREATE TABLE statements plus INSERT
blocks, optionally embedded in a markdown document. DuckDB will not accept
MySQL's dialect verbatim, so the DDL is translated on the way in.

Only two statement kinds are executed - CREATE TABLE and INSERT. Anything else
in the file is ignored, so a schema document full of prose and diagrams loads
exactly as cleanly as a plain .sql dump.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

SQL_SUFFIXES = {".sql", ".md"}

# MySQL constructs DuckDB does not accept, and what to do with them
_TABLE_OPTIONS = re.compile(r"\)\s*ENGINE\s*=.*?;", re.IGNORECASE | re.DOTALL)
_ENUM = re.compile(r"\bENUM\s*\([^)]*\)", re.IGNORECASE)
_UNSIGNED = re.compile(r"\bUNSIGNED\b", re.IGNORECASE)
_AUTO_INC = re.compile(r"\bAUTO_INCREMENT\b", re.IGNORECASE)
_TIMESTAMP_PRECISION = re.compile(r"\bTIMESTAMP\s*\(\s*\d+\s*\)", re.IGNORECASE)
_CONSTRAINT_LINE = re.compile(
    r"^\s*(FOREIGN\s+KEY|CONSTRAINT|UNIQUE\s+KEY|KEY|INDEX)\b.*?,?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BACKTICKS = re.compile(r"`")
# a leading-zero integer literal such as program_id 04
_LEADING_ZERO_INT = re.compile(r"(?<=[,(\s])0(\d+)(?=[,)\s])")


def extract_statements(text: str) -> tuple[list[str], list[str]]:
    """Pull CREATE TABLE and INSERT statements out of raw text or markdown."""
    # markdown fences are irrelevant to the parser; strip the markers only
    cleaned = re.sub(r"^```\w*\s*$", "", text, flags=re.MULTILINE)
    creates = re.findall(r"CREATE\s+TABLE\s+.*?;", cleaned, re.IGNORECASE | re.DOTALL)
    inserts = re.findall(r"INSERT\s+INTO\s+.*?;", cleaned, re.IGNORECASE | re.DOTALL)
    return creates, inserts


def translate_ddl(statement: str) -> str:
    """MySQL CREATE TABLE -> something DuckDB will accept."""
    out = _BACKTICKS.sub('"', statement)
    out = _TABLE_OPTIONS.sub(");", out)
    out = _ENUM.sub("VARCHAR", out)
    out = _UNSIGNED.sub("", out)
    out = _AUTO_INC.sub("", out)
    out = _TIMESTAMP_PRECISION.sub("TIMESTAMP", out)
    # FK and index clauses are not enforced here and DuckDB rejects some of them
    out = _CONSTRAINT_LINE.sub("", out)
    # a trailing comma left behind by a removed constraint line
    out = re.sub(r",\s*\)", "\n)", out)
    return out


def translate_insert(statement: str) -> str:
    out = _BACKTICKS.sub('"', statement)
    # 04 is a valid MySQL int literal; DuckDB parses it fine, but octal-looking
    # values are normalised so the loaded value is unambiguous
    out = _LEADING_ZERO_INT.sub(r"\1", out)
    return out


def quote_table_names(statement: str, reserved: set[str]) -> str:
    """`transaction` is a reserved word in DuckDB; quote it wherever it names a table."""
    for name in reserved:
        statement = re.sub(
            rf'(CREATE\s+TABLE\s+|INSERT\s+INTO\s+)(?!")({name})\b',
            rf'\1"{name}"',
            statement,
            flags=re.IGNORECASE,
        )
    return statement


RESERVED_TABLE_NAMES = {"transaction", "order", "group", "table", "select", "values"}


def load_sql_file(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    skip_existing: set[str] | None = None,
) -> dict[str, int]:
    """Execute every CREATE TABLE and INSERT in one file. Returns rows per table.

    A directory can legitimately hold the same schema twice - a document and a
    dump extracted from it, say - so tables already loaded from an earlier file
    are skipped rather than raising.
    """
    skip_existing = skip_existing or set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    creates, inserts = extract_statements(text)
    loaded: dict[str, int] = {}

    for statement in creates:
        name = re.search(r"CREATE\s+TABLE\s+\"?(\w+)\"?", statement, re.IGNORECASE)
        if name and name.group(1) in skip_existing:
            continue
        prepared = quote_table_names(translate_ddl(statement), RESERVED_TABLE_NAMES)
        try:
            connection.execute(prepared)
        except duckdb.Error as exc:
            raise ValueError(f"could not create table from {path.name}: {exc}") from exc

    for statement in inserts:
        prepared = quote_table_names(translate_insert(statement), RESERVED_TABLE_NAMES)
        match = re.search(r"INSERT\s+INTO\s+\"?(\w+)\"?", prepared, re.IGNORECASE)
        table = match.group(1) if match else "?"
        if table in skip_existing:
            continue
        try:
            connection.execute(prepared)
            loaded[table] = loaded.get(table, 0) + prepared.count("),(") + prepared.count("),\n")  # rough
        except duckdb.Error as exc:
            raise ValueError(f"insert into {table} failed ({path.name}): {exc}") from exc

    # report real counts rather than the rough parse above
    for table in list(loaded):
        try:
            loaded[table] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        except duckdb.Error:
            pass
    return loaded


def load_sql_directory(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    prefix: str = "",
) -> dict[str, int]:
    """Load every SQL/markdown file in a directory.

    `prefix` renames the loaded tables (e.g. "_source_"), so SQL-delivered data
    lands behind the same private names the CSV path uses and the safe public
    views cover both identically.
    """
    totals: dict[str, int] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SQL_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"\bINSERT\s+INTO\b", text, re.IGNORECASE):
            continue  # a markdown file with no data in it
        loaded = load_sql_file(connection, path, skip_existing=set(totals))
        for table, rows in loaded.items():
            if table in totals:
                continue
            if prefix:
                # rename rather than alias: the public safe view takes the plain
                # name, and a table already sitting there would collide with it
                connection.execute(f'ALTER TABLE "{table}" RENAME TO "{prefix}{table}"')
            totals[table] = rows
    return totals
