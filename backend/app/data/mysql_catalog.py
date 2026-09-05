"""MySQL-backed, introspected analytical catalog.

CSV is accepted only as an ingestion format. Chat queries and schema discovery
always use the connected MySQL database. The catalog is cached after extraction
and refreshed explicitly after an upload or schema deployment.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any

import mysql.connector

from app.data.catalog import safe_name


class DatabaseQueryError(ValueError):
    pass


class QueryPolicyError(ValueError):
    pass


class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def description(self):
        return self.cursor.description

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class MySQLConnectionAdapter:
    """Small execute-style wrapper used by the existing grounded engine."""

    def __init__(self, connection, max_query_cost: float, explain_analyze: bool):
        self.raw = connection
        self.max_query_cost = max_query_cost
        self.explain_analyze = explain_analyze

    @staticmethod
    def _mysql_sql(sql: str) -> str:
        sql = re.sub(r'"([a-zA-Z0-9_]+)"', r'`\1`', sql)
        sql = re.sub(r"\bAS\s+VARCHAR\b", "AS CHAR", sql, flags=re.IGNORECASE)
        return sql.replace("?", "%s")

    def execute(self, sql: str, parameters: list[Any] | tuple[Any, ...] | None = None):
        # SQL is generated internally after allowlist validation. Translate the
        # engine's neutral identifier/parameter syntax to MySQL's DB-API syntax.
        sql = self._mysql_sql(sql)
        cursor = self.raw.cursor()
        try:
            cursor.execute(sql, tuple(parameters or ()))
        except mysql.connector.Error as exc:
            cursor.close()
            raise DatabaseQueryError("the validated query could not be executed by MySQL") from exc
        return CursorAdapter(cursor)

    @staticmethod
    def _query_cost(node: Any) -> float | None:
        if isinstance(node, dict):
            cost = node.get("query_cost")
            if cost is not None:
                try:
                    return float(cost)
                except (TypeError, ValueError):
                    pass
            for value in node.values():
                found = MySQLConnectionAdapter._query_cost(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = MySQLConnectionAdapter._query_cost(value)
                if found is not None:
                    return found
        return None

    def validate_cost(self, sql: str, parameters: list[Any]) -> float | None:
        mysql_sql = self._mysql_sql(sql)
        cursor = self.raw.cursor()
        try:
            cursor.execute("EXPLAIN FORMAT=JSON " + mysql_sql, tuple(parameters))
            payload = cursor.fetchone()[0]
            cost = self._query_cost(json.loads(payload))
            if cost is not None and cost > self.max_query_cost:
                raise QueryPolicyError(
                    f"estimated MySQL query cost {cost:.1f} exceeds the configured limit"
                )
            if self.explain_analyze:
                cursor.execute("EXPLAIN ANALYZE " + mysql_sql, tuple(parameters))
                cursor.fetchall()
            return cost
        except mysql.connector.Error as exc:
            raise DatabaseQueryError("MySQL could not explain the validated query") from exc
        finally:
            cursor.close()

    def close(self) -> None:
        self.raw.close()


class MySQLDatasetCatalog:
    ID_COLUMN_RE = re.compile(r"(^|_)(id|ids|code|codes|ref|refs|number|no)$", re.IGNORECASE)
    SENSITIVE_RE = re.compile(r"(^|_)(utr|password|secret|token|api_key)(_|$)", re.IGNORECASE)

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        upload_directory: str,
        data_max_date: str | None = None,
        max_result_rows: int = 200,
        query_timeout_ms: int = 5_000,
        max_query_cost: float = 100_000.0,
        explain_analyze: bool = False,
        require_time_filter_tables: set[str] | None = None,
    ):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", database):
            raise ValueError("MySQL database name contains unsupported characters")
        self.options = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
        }
        self.database = database
        self.upload_directory = Path(upload_directory)
        self.data_max_date = data_max_date
        self.max_result_rows = max_result_rows
        self.query_timeout_ms = query_timeout_ms
        self.max_query_cost = max_query_cost
        self.explain_analyze = explain_analyze
        self.require_time_filter_tables = require_time_filter_tables or set()
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        self._catalog_cache: dict[str, list[dict[str, str]]] | None = None
        self._lock = RLock()

    def _raw_connection(self):
        connection = mysql.connector.connect(
            **self.options,
            connection_timeout=max(1, self.query_timeout_ms // 1000),
        )
        cursor = connection.cursor()
        cursor.execute("SET SESSION MAX_EXECUTION_TIME = %s", (self.query_timeout_ms,))
        cursor.close()
        return connection

    def connection(self) -> MySQLConnectionAdapter:
        return MySQLConnectionAdapter(
            self._raw_connection(), self.max_query_cost, self.explain_analyze
        )

    def validate_plan(self, plan) -> None:
        if plan.dataset not in self.require_time_filter_tables:
            return
        columns = {item["name"]: item["type"].upper() for item in self.describe().get(plan.dataset, [])}
        has_time_scope = any(
            item.operator in {"gte", "gt", "lte", "lt"}
            and any(token in columns.get(item.column, "") for token in ("DATE", "TIME"))
            for item in plan.filters
        )
        point_lookup = any(
            item.operator == "eq"
            and (
                item.column in {"transaction_id", "transaction_reference_id"}
                or item.column.endswith("_reference_id")
            )
            for item in plan.filters
        )
        if not has_time_scope and not point_lookup:
            raise QueryPolicyError(
                f"broad queries on {plan.dataset} require a date/time filter; "
                "an exact transaction/reference lookup is exempt"
            )

    def refresh(self) -> dict[str, list[dict[str, str]]]:
        with self._lock:
            self._catalog_cache = self._extract_schema()
            return self._catalog_cache

    def describe(self) -> dict[str, list[dict[str, str]]]:
        with self._lock:
            if self._catalog_cache is None:
                self._catalog_cache = self._extract_schema()
            return self._catalog_cache

    def schema_vocabulary(self) -> set[str]:
        """Build planning vocabulary from metadata, never production rows."""
        words: set[str] = set()
        for table, columns in self.describe().items():
            words.update(re.findall(r"[a-zA-Z]+", table.lower()))
            for column in columns:
                words.update(re.findall(r"[a-zA-Z]+", column["name"].lower()))
                if description := column.get("description"):
                    words.update(re.findall(r"[a-zA-Z]+", description.lower()))
        return words

    def entity_values(self) -> list[str]:
        """Avoid unbounded DISTINCT scans; filters are verified by MySQL."""
        return []

    def _extract_schema(self) -> dict[str, list[dict[str, str]]]:
        connection = self._raw_connection()
        cursor = connection.cursor()
        cursor.execute(
            """SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT
                 FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME NOT LIKE 'source\\_%'
                ORDER BY TABLE_NAME, ORDINAL_POSITION""",
            (self.database,),
        )
        catalog: dict[str, list[dict[str, str]]] = {}
        for table, column, column_type, comment in cursor.fetchall():
            if self.SENSITIVE_RE.search(column) or column.lower() == "account_number":
                continue
            item = {"name": column, "type": column_type}
            if comment:
                item["description"] = comment
            catalog.setdefault(table, []).append(item)
        cursor.close()
        connection.close()
        return {table: columns for table, columns in catalog.items() if columns}

    def date_bounds(self) -> tuple[str | None, str | None]:
        # INFORMATION_SCHEMA extraction must stay metadata-only. MIN/MAX scans
        # over every date column are unacceptable on the real high-row database.
        return None, self.data_max_date

    def column_date_bounds(self) -> dict[str, tuple[str, str]]:
        return {}

    @classmethod
    def _column_type(cls, name: str, values: list[str]) -> str:
        nonempty = [value.strip() for value in values if value is not None and value.strip()]
        if cls.ID_COLUMN_RE.search(name) or not nonempty:
            return "VARCHAR(255)"
        try:
            for value in nonempty:
                int(value)
            return "BIGINT"
        except ValueError:
            pass
        try:
            for value in nonempty:
                Decimal(value)
            return "DECIMAL(20,6)"
        except InvalidOperation:
            pass
        try:
            for value in nonempty:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "DATETIME"
        except ValueError:
            return "TEXT" if max(map(len, nonempty)) > 255 else "VARCHAR(255)"

    def import_csv(self, filename: str, content: bytes) -> str:
        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are accepted for ingestion")
        table = f"source_{safe_name(Path(filename).stem)}"
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV must contain a header row")
        columns = [safe_name(name) for name in reader.fieldnames]
        if len(columns) != len(set(columns)):
            raise ValueError("CSV headers must remain unique after name normalization")
        rows = [[row[name] if row[name] != "" else None for name in reader.fieldnames] for row in reader]
        types = [self._column_type(name, [row[index] for row in rows]) for index, name in enumerate(columns)]

        connection = self._raw_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
            definitions = ", ".join(f"`{name}` {kind} NULL" for name, kind in zip(columns, types, strict=True))
            cursor.execute(f"CREATE TABLE `{table}` ({definitions})")
            if rows:
                placeholders = ", ".join(["%s"] * len(columns))
                cursor.executemany(f"INSERT INTO `{table}` VALUES ({placeholders})", rows)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

        destination = self.upload_directory / f"{safe_name(Path(filename).stem)}.csv"
        destination.write_bytes(content)
        self.create_safe_views()
        self.refresh()
        return destination.name

    def import_directory(self, directory: str) -> list[str]:
        imported = []
        for path in sorted(Path(directory).glob("*.csv")):
            imported.append(self.import_csv(path.name, path.read_bytes()))
        return imported

    def provision_read_user(self, username: str, password: str) -> None:
        """Local-demo provisioning. Production credentials are supplied by TBX."""
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", username):
            raise ValueError("MySQL read username contains unsupported characters")
        escaped_password = password.replace("'", "''")
        connection = self._raw_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{username}'@'%' IDENTIFIED BY '{escaped_password}'"
            )
            cursor.execute(f"GRANT SELECT ON `{self.database}`.* TO '{username}'@'%'")
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def _ensure_index(self, cursor, table: str, name: str, columns: list[str]) -> None:
        cursor.execute(
            """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s""",
            (self.database, table),
        )
        available = {row[0] for row in cursor.fetchall()}
        if not set(columns) <= available:
            return
        cursor.execute(
            """SELECT 1 FROM INFORMATION_SCHEMA.STATISTICS
               WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1""",
            (self.database, table, name),
        )
        if cursor.fetchone() is None:
            quoted = ", ".join(f"`{column}`" for column in columns)
            cursor.execute(f"CREATE INDEX `{name}` ON `{table}` ({quoted})")

    def create_safe_views(self) -> None:
        """Expose privacy-safe views; add optional TBX joins when those sources exist."""
        connection = self._raw_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME LIKE 'source\\_%'",
                (self.database,),
            )
            sources = {row[0] for row in cursor.fetchall()}
            for source in sources:
                public = source.removeprefix("source_")
                cursor.execute(
                    """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION""",
                    (self.database, source),
                )
                names = [row[0] for row in cursor.fetchall()]
                selections = []
                for name in names:
                    if self.SENSITIVE_RE.search(name):
                        if name.lower() == "utr_number":
                            selections.append(f"(`{name}` IS NOT NULL AND TRIM(`{name}`) <> '') AS `utr_available`")
                        continue
                    if name.lower() == "account_number":
                        selections.append(f"RIGHT(CAST(`{name}` AS CHAR), 4) AS `account_last4`")
                        continue
                    selections.append(f"`{name}`")
                if selections:
                    cursor.execute(
                        f"CREATE OR REPLACE VIEW `{public}` AS "
                        f"SELECT {', '.join(selections)} FROM `{source}`"
                    )

            if {"source_bank", "source_account", "source_transaction"} <= sources:
                # Cover the demonstrated lookup, period, type, bank/account join and
                # aggregate paths. Production indexes must be reviewed against TBX
                # workload telemetry and EXPLAIN output.
                self._ensure_index(cursor, "source_bank", "idx_bank_code", ["bank_code"])
                self._ensure_index(cursor, "source_account", "idx_account_id", ["account_id"])
                self._ensure_index(
                    cursor, "source_account", "idx_account_bank", ["bank_code", "account_id"]
                )
                self._ensure_index(
                    cursor, "source_transaction", "idx_txn_reference",
                    ["transaction_reference_id"]
                )
                self._ensure_index(
                    cursor, "source_transaction", "idx_txn_account_date",
                    ["account_id", "transaction_date"]
                )
                self._ensure_index(
                    cursor, "source_transaction", "idx_txn_type_date_amount",
                    ["transaction_type", "transaction_date", "transaction_amount"]
                )
                cursor.execute("""CREATE OR REPLACE VIEW `account` AS
                SELECT CAST(a.account_id AS CHAR) account_id, CAST(a.entity_id AS CHAR) entity_id,
                       RIGHT(CAST(a.account_number AS CHAR),4) account_last4, a.program_id,
                       a.available_balance, CAST(a.bank_code AS CHAR) bank_code,
                       CAST(b.bank_name AS CHAR) bank_name
                  FROM source_account a LEFT JOIN source_bank b ON a.bank_code=b.bank_code""")
                cursor.execute("""CREATE OR REPLACE VIEW `transaction` AS
                SELECT CAST(t.transaction_id AS CHAR) transaction_id,
                       CAST(t.account_id AS CHAR) account_id, CAST(a.entity_id AS CHAR) entity_id,
                       CAST(a.bank_code AS CHAR) bank_code, CAST(b.bank_name AS CHAR) bank_name,
                       a.program_id, RIGHT(CAST(a.account_number AS CHAR),4) account_last4,
                       t.transaction_date, CAST(t.transaction_type AS CHAR) transaction_type,
                       CAST(t.description AS CHAR) description, t.transaction_amount,
                       CAST(t.transaction_reference_id AS CHAR) transaction_reference_id,
                       (t.utr_number IS NOT NULL AND TRIM(CAST(t.utr_number AS CHAR)) <> '') utr_available
                  FROM source_transaction t LEFT JOIN source_account a ON t.account_id=a.account_id
                  LEFT JOIN source_bank b ON a.bank_code=b.bank_code""")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()
