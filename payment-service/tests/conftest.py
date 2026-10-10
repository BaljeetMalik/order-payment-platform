import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.migrations import run_migrations
from app.repository import InMemoryRepository, PostgresRepository

# Defaults to "<DATABASE_URL database>_test" so tests never touch the app's data.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or make_url(settings.DATABASE_URL).set(
    database=f"{make_url(settings.DATABASE_URL).database}_test"
).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def pg_session_factory():
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except OperationalError as exc:
        pytest.skip(f"Postgres test database unavailable: {exc.orig}")
    run_migrations(TEST_DATABASE_URL)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture(params=["memory", "postgres"])
def repository(request):
    if request.param == "memory":
        return InMemoryRepository()
    factory = request.getfixturevalue("pg_session_factory")
    with factory() as session:
        session.execute(text("TRUNCATE processed_events, outbox, idempotency_keys, refunds, payments"))
        session.commit()
    return PostgresRepository(factory)
