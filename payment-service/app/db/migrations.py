from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migrations(database_url: str | None = None) -> None:
    """Apply all pending Alembic migrations (alembic upgrade head).

    database_url overrides settings.DATABASE_URL (used by the tests).
    """
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    if database_url:
        config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
