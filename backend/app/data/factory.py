from functools import lru_cache

from app.config import Settings, get_settings
from app.data.mysql_catalog import MySQLDatasetCatalog


@lru_cache
def get_dataset_catalog() -> MySQLDatasetCatalog:
    return create_dataset_catalog(get_settings())


def create_dataset_catalog(settings: Settings, *, write: bool = False) -> MySQLDatasetCatalog:
    return MySQLDatasetCatalog(
        host=settings.mysql_write_host if write else settings.mysql_read_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_write_user if write else settings.mysql_read_user,
        password=settings.mysql_write_password if write else settings.mysql_read_password,
        upload_directory=settings.resolved_upload_directory,
        data_max_date=settings.data_max_date or None,
        max_result_rows=settings.max_result_rows,
        query_timeout_ms=settings.mysql_query_timeout_ms,
        max_query_cost=settings.mysql_max_query_cost,
        explain_analyze=settings.mysql_explain_analyze,
        require_time_filter_tables=settings.time_filter_tables,
    )
