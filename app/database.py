from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Boolean, select
import os

DATABASE_URL = os.environ.get("MANAGER_DATABASE_URL", "sqlite+aiosqlite:////app/config/modelmanager-settings.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)
    is_secret = Column(Boolean, default=False)

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
