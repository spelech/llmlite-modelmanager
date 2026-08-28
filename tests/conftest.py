import pytest
from app.database import Base, DATABASE_URL
from sqlalchemy import create_engine

@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    sync_url = DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
