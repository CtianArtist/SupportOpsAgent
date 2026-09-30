from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import make_engine
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_provider="mock",
        SUPPORTOPS_DATABASE_URL="sqlite://",
        retry_base_delay_seconds=0,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    application = create_app(settings=settings, engine=make_engine("sqlite://"))
    with TestClient(application) as test_client:
        yield test_client