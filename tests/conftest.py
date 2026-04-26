from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401


@pytest.fixture(scope="session")
def integration_engine():
    engine = create_engine(settings.test_database_url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Integration DB unavailable: {exc}")

    Base.metadata.create_all(bind=engine)
    yield engine
    # Avoid destructive teardown when tests are pointed at the same DB used by the app.
    if settings.test_database_url != settings.database_url:
        Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(integration_engine) -> Generator[Session, None, None]:
    testing_session_local = sessionmaker(bind=integration_engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    transaction = session.begin_nested()
    try:
        yield session
    finally:
        transaction.rollback()
        session.close()
