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

    def connection(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(":memory:")
        for path in sorted(self.directory.glob("*.csv")):
            view = safe_name(path.stem)
            escaped = str(path.resolve()).replace("'", "''")
            connection.execute(
                f'CREATE VIEW "{view}" AS SELECT * FROM read_csv_auto(\'{escaped}\', normalize_names=true)'
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

    def save_upload(self, filename: str, content: bytes) -> str:
        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are accepted in the starter")
        destination = self.directory / f"{safe_name(Path(filename).stem)}.csv"
        destination.write_bytes(content)
        return destination.name

