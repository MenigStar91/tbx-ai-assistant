"""Import deterministic sample CSVs into MySQL before the API starts."""

from app.config import get_settings
from app.data.factory import create_dataset_catalog


def main() -> None:
    settings = get_settings()
    catalog = create_dataset_catalog(settings, write=True)
    imported = catalog.import_directory(settings.resolved_seed_directory)
    catalog.provision_read_user(settings.mysql_read_user, settings.mysql_read_password)
    print(f"Imported {len(imported)} sample dataset(s) into MySQL")


if __name__ == "__main__":
    main()
