from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migrations() -> None:
    """Apply all pending Alembic migrations (alembic upgrade head)."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
