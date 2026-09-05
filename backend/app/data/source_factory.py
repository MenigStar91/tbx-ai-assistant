"""Pick the data source: files through DuckDB, or MySQL read-only."""

from __future__ import annotations

from app.config import Settings
from app.data.catalog import DatasetCatalog
from app.data.mysql_source import MySQLReadOnlyCatalog


def create_catalog(settings: Settings):
    if settings.data_backend.lower() == "mysql":
        return MySQLReadOnlyCatalog(
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_database,
            user=settings.mysql_user,
            password=settings.mysql_password,
        )
    return DatasetCatalog(settings.resolved_data_directory)
