import re
from pathlib import Path
from typing import Any

import duckdb


def safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if not name or name[0].isdigit():
        name = f"dataset_{name}"
    return name


class DatasetCatalog:
    """Discovers TBX CSV files at runtime; no unpublished schema is assumed."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    # Identifier columns look numeric to DuckDB's sniffer whenever the sample
    # happens to be all digits. Once inferred as BIGINT, the first comparison
    # against a string id raises a conversion error and takes the request with
    # it. Reading them as VARCHAR costs nothing and removes the whole class.
    ID_COLUMN_RE = re.compile(r"(^|_)(id|ids|code|codes|ref|refs|number|no)$", re.IGNORECASE)

    def _forced_varchar(self, path: Path) -> dict[str, str]:
        try:
            header = path.open("r", encoding="utf-8", errors="ignore").readline()
        except OSError:
            return {}
        columns = [c.strip().strip('"').lower().replace(" ", "_") for c in header.split(",")]
        return {c: "VARCHAR" for c in columns if c and self.ID_COLUMN_RE.search(c)}

    def connection(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(":memory:")
        for path in sorted(self.directory.glob("*.csv")):
            view = safe_name(path.stem)
            escaped = str(path.resolve()).replace("'", "''")
            forced = self._forced_varchar(path)
            # DuckDB rejects an empty types={} with a parser error, so omit it
            types = f", types={forced!r}" if forced else ""
            connection.execute(
                f'CREATE VIEW "{view}" AS SELECT * FROM '
                f"read_csv_auto('{escaped}', normalize_names=true{types})"
            )
        return connection

    def describe(self) -> dict[str, list[dict[str, str]]]:
        connection = self.connection()
        catalog: dict[str, list[dict[str, str]]] = {}
        for (name,) in connection.execute("SHOW TABLES").fetchall():
            rows = connection.execute(f'DESCRIBE "{name}"').fetchall()
            catalog[name] = [{"name": row[0], "type": row[1]} for row in rows]
        connection.close()
        return catalog

    def date_bounds(self) -> tuple[str | None, str | None]:
        """Earliest and latest date anywhere in the loaded data.

        Relative periods must anchor here, not to datetime.today(). A finance
        dataset is historical: if it ends in June and today is September, "last
        month" against the wall clock selects an empty window and the assistant
        confidently answers zero. Anchoring to the data makes "last month" mean
        the last month the data actually has.
        """
        connection = self.connection()
        lo: str | None = None
        hi: str | None = None
        try:
            for (table,) in connection.execute("SHOW TABLES").fetchall():
                for row in connection.execute(f'DESCRIBE "{table}"').fetchall():
                    column, column_type = row[0], row[1].upper()
                    if "DATE" not in column_type and "TIMESTAMP" not in column_type:
                        continue
                    try:
                        low, high = connection.execute(
                            f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"'
                        ).fetchone()
                    except duckdb.Error:
                        continue
                    for value in (low, high):
                        if value is None:
                            continue
                        text = str(value)[:10]
                        lo = text if lo is None or text < lo else lo
                        hi = text if hi is None or text > hi else hi
        finally:
            connection.close()
        return lo, hi

    def column_date_bounds(self) -> dict[str, tuple[str, str]]:
        """Bounds for every date column, keyed "table.column".

        Per column, not global: an audit field like last_reviewed_at can run
        weeks past the last payout_date, and anchoring "last month" to the
        global maximum then selects a month the payouts table does not reach.
        """
        connection = self.connection()
        bounds: dict[str, tuple[str, str]] = {}
        try:
            for (table,) in connection.execute("SHOW TABLES").fetchall():
                for row in connection.execute(f'DESCRIBE "{table}"').fetchall():
                    column, column_type = row[0], row[1].upper()
                    if "DATE" not in column_type and "TIMESTAMP" not in column_type:
                        continue
                    try:
                        low, high = connection.execute(
                            f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"'
                        ).fetchone()
                    except duckdb.Error:
                        continue
                    if low is not None and high is not None:
                        bounds[f"{table}.{column}"] = (str(low)[:10], str(high)[:10])
        finally:
            connection.close()
        return bounds

    def save_upload(self, filename: str, content: bytes) -> str:
        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are accepted in the starter")
        destination = self.directory / f"{safe_name(Path(filename).stem)}.csv"
        destination.write_bytes(content)
        return destination.name

