from functools import lru_cache

from app.config import Settings, get_settings
from app.data.mysql_catalog import MySQLDatasetCatalog


@lru_cache
def get_dataset_catalog() -> MySQLDatasetCatalog:
    return create_dataset_catalog(get_settings())


def create_dataset_catalog(settings: Settings) -> MySQLDatasetCatalog:
    return MySQLDatasetCatalog(
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        user=settings.mysql_user,
        password=settings.mysql_password,
        upload_directory=settings.resolved_upload_directory,
        data_max_date=settings.data_max_date or None,
    )
