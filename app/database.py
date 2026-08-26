from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Boolean, Float, Integer, select
import os
import time
import json
from typing import Dict, List, Optional

DEFAULT_DB_DIR = "/app/config" if os.path.exists("/app/config") else "."
DATABASE_URL = os.environ.get("MANAGER_DATABASE_URL", f"sqlite+aiosqlite:///{os.path.abspath(DEFAULT_DB_DIR)}/modelmanager-settings.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)
    is_secret = Column(Boolean, default=False)

class DiscoveredModel(Base):
    __tablename__ = "discovered_models"
    id = Column(String, primary_key=True)
    provider = Column(String)
    brand = Column(String)
    name = Column(String)
    tier = Column(String)  # cheap, moderate, frontier
    first_seen = Column(Float, default=time.time)
    last_seen = Column(Float, default=time.time)
    is_healthy = Column(Boolean, default=True)
    last_health_check = Column(Float, nullable=True)
    last_error = Column(String, nullable=True)
    popularity = Column(Integer, default=999)
    details_json = Column(String, nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_all_settings():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Setting))
        return {s.key: s.value for s in result.scalars().all()}

async def set_setting(key: str, value: str, is_secret: bool = False):
    async with AsyncSessionLocal() as session:
        setting = await session.get(Setting, key)
        if setting:
            setting.value = value
            setting.is_secret = is_secret
        else:
            setting = Setting(key=key, value=value, is_secret=is_secret)
            session.add(setting)
        await session.commit()

async def get_setting(key: str, default=None):
    async with AsyncSessionLocal() as session:
        setting = await session.get(Setting, key)
        return setting.value if setting else default

async def get_all_discovered_models() -> List[DiscoveredModel]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DiscoveredModel))
        return list(result.scalars().all())

async def get_discovered_model(model_id: str) -> Optional[DiscoveredModel]:
    async with AsyncSessionLocal() as session:
        return await session.get(DiscoveredModel, model_id)

async def upsert_discovered_models(models_data: List[Dict]) -> List[Dict]:
    """
    Upserts discovered models. Returns a list of newly discovered models (for alerting).
    """
    new_models = []
    now = time.time()
    async with AsyncSessionLocal() as session:
        for m in models_data:
            mid = m["id"]
            existing = await session.get(DiscoveredModel, mid)
            if existing:
                existing.last_seen = now
                existing.name = m.get("name", existing.name)
                existing.brand = m.get("brand", existing.brand)
                existing.tier = m.get("tier", existing.tier)
                existing.popularity = m.get("popularity", existing.popularity)
                existing.details_json = json.dumps(m)
            else:
                new_entry = DiscoveredModel(
                    id=mid,
                    provider=m.get("provider", mid.split("/")[0] if "/" in mid else "unknown"),
                    brand=m.get("brand", "other"),
                    name=m.get("name", mid),
                    tier=m.get("tier", "moderate"),
                    first_seen=now,
                    last_seen=now,
                    is_healthy=True,
                    popularity=m.get("popularity", 999),
                    details_json=json.dumps(m)
                )
                session.add(new_entry)
                new_models.append(m)
        await session.commit()
    return new_models

async def update_model_health(model_id: str, is_healthy: bool, error: Optional[str] = None):
    now = time.time()
    async with AsyncSessionLocal() as session:
        model = await session.get(DiscoveredModel, model_id)
        if model:
            model.is_healthy = is_healthy
            model.last_health_check = now
            model.last_error = error
        else:
            model = DiscoveredModel(
                id=model_id,
                provider=model_id.split("/")[0] if "/" in model_id else "unknown",
                brand="other",
                name=model_id,
                tier="moderate",
                first_seen=now,
                last_seen=now,
                is_healthy=is_healthy,
                last_health_check=now,
                last_error=error
            )
            session.add(model)
        await session.commit()

async def get_unhealthy_models() -> List[DiscoveredModel]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DiscoveredModel).where(DiscoveredModel.is_healthy == False))
        return list(result.scalars().all())
