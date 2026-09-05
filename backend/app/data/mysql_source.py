"""Read-only MySQL catalog.

TBX grants SELECT on three tables and nothing else, so this connects, reads,
and never writes: no CREATE VIEW, no CREATE INDEX, no DROP, no INSERT. The
joined and masked surface the planner queries travels with each statement as an
inlined projection (app/data/projections.py) instead of being a view in their
database.

The connection object mimics the DuckDB one the query engine already uses -
`execute(sql, params)` returning something with `.description` and `.fetchall()`
- so nothing downstream needs to know which engine it is talking to.
"""

from __future__ import annotations

import mysql.connector

from app.data.dialect import MYSQL_SESSION_SETUP, to_driver_params
from app.data.projections import PROJECTIONS, projection_sql


class _Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _Connection:
    """DuckDB-shaped wrapper over a MySQL connection."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql: str, parameters=None):
        # buffered: the engine issues several statements per answer, and an
        # unbuffered cursor leaves the previous result set unread on the wire
        cursor = self._connection.cursor(buffered=True)
        cursor.execute(to_driver_params(sql), tuple(parameters or ()))
        return _Cursor(cursor)

    def close(self) -> None:
        try:
            self._connection.close()
        except mysql.connector.Error:
            pass


class MySQLReadOnlyCatalog:
    """Exposes the same three datasets as the file-based catalog, from MySQL."""

    # the projection is inlined per query, because we may not create views here
    inline_sources = True
    source_prefix = ""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self._settings = dict(host=host, port=port, database=database,
                              user=user, password=password, autocommit=True)
        self._catalog: dict[str, list[dict[str, str]]] | None = None

    def _connect(self):
        connection = mysql.connector.connect(**self._settings)
        cursor = connection.cursor(buffered=True)
        for statement in MYSQL_SESSION_SETUP:
            cursor.execute(statement)
        cursor.close()
        return connection

    def connection(self) -> _Connection:
        return _Connection(self._connect())

    def describe(self) -> dict[str, list[dict[str, str]]]:
        """Columns of each safe dataset, read by asking for zero rows of it.

        Cached: the shape does not change under us, and re-deriving it per
        request would mean a round trip before every question.
        """
        if self._catalog is not None:
            return self._catalog

        catalog: dict[str, list[dict[str, str]]] = {}
        connection = self.connection()
        try:
            for dataset in PROJECTIONS:
                cursor = connection.execute(
                    f"SELECT * FROM ( {projection_sql(dataset, self.source_prefix)} ) "
                    f'AS "{dataset}" LIMIT 0'
                )
                catalog[dataset] = [
                    {"name": column[0], "type": _type_name(column[1])}
                    for column in cursor.description
                ]
        finally:
            connection.close()
        self._catalog = catalog
        return catalog

    def date_bounds(self) -> tuple[str | None, str | None]:
        lo, hi = None, None
        connection = self.connection()
        try:
            for key, (lo_v, hi_v) in self.column_date_bounds().items():  # noqa: B007
                lo = lo_v if lo is None or lo_v < lo else lo
                hi = hi_v if hi is None or hi_v > hi else hi
        finally:
            connection.close()
        return lo, hi

    def column_date_bounds(self) -> dict[str, tuple[str, str]]:
        bounds: dict[str, tuple[str, str]] = {}
        connection = self.connection()
        try:
            for dataset, columns in self.describe().items():
                source = f'( {projection_sql(dataset, self.source_prefix)} ) AS "{dataset}"'
                for column in columns:
                    if "DATE" not in column["type"].upper() and "TIME" not in column["type"].upper():
                        continue
                    row = connection.execute(
                        f'SELECT MIN("{column["name"]}"), MAX("{column["name"]}") FROM {source}'
                    ).fetchone()
                    if row and row[0] is not None and row[1] is not None:
                        bounds[f'{dataset}.{column["name"]}'] = (str(row[0])[:10], str(row[1])[:10])
        finally:
            connection.close()
        return bounds


# mysql.connector reports column types as FieldType integers
_FIELD_TYPES = {
    1: "TINYINT", 2: "SMALLINT", 3: "INT", 4: "FLOAT", 5: "DOUBLE", 7: "TIMESTAMP",
    8: "BIGINT", 9: "INT", 10: "DATE", 11: "TIME", 12: "DATETIME", 13: "YEAR",
    246: "DECIMAL", 252: "TEXT", 253: "VARCHAR", 254: "CHAR",
}


def _type_name(code) -> str:
    return _FIELD_TYPES.get(code, "VARCHAR")
