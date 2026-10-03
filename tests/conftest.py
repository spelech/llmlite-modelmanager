import pytest
from app.database import Base, DATABASE_URL
from sqlalchemy import create_engine

@pytest.fixture(autouse=True, scope="session")
def setup_test_db():
    from sqlalchemy import text
    sync_url = DATABASE_URL.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    with sync_engine.connect() as conn:
        for col, col_type in [
            ("previous_price_prompt", "FLOAT"),
            ("previous_price_completion", "FLOAT"),
            ("price_last_changed", "FLOAT"),
            ("price_change_pct", "FLOAT"),
            ("price_change_direction", "VARCHAR")
        ]:
            try:
                conn.execute(text(f"ALTER TABLE discovered_models ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass
