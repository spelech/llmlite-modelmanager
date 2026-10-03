from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Boolean, Float, Integer, select
import os
import time
import json
from typing import Dict, List, Optional, Any

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
    previous_price_prompt = Column(Float, nullable=True)
    previous_price_completion = Column(Float, nullable=True)
    price_last_changed = Column(Float, nullable=True)
    price_change_pct = Column(Float, nullable=True)
    price_change_direction = Column(String, nullable=True)

async def init_db():
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate new columns on existing database
        for col, col_type in [
            ("previous_price_prompt", "FLOAT"),
            ("previous_price_completion", "FLOAT"),
            ("price_last_changed", "FLOAT"),
            ("price_change_pct", "FLOAT"),
            ("price_change_direction", "VARCHAR")
        ]:
            try:
                await conn.execute(text(f"ALTER TABLE discovered_models ADD COLUMN {col} {col_type}"))
            except Exception:
                pass  # Column already exists

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

async def upsert_discovered_models(models_data: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Upserts discovered models. Returns dict with:
      'new_models': newly discovered models (for trending alerts)
      'price_changed_models': models with notable price drops or increases (>1%)
    """
    new_models = []
    price_changed_models = []
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

                # Check for pricing change
                new_pricing = m.get("pricing", {})
                new_prompt_1m = float(new_pricing.get("prompt_1m", 0.0) or 0.0)
                new_comp_1m = float(new_pricing.get("completion_1m", 0.0) or 0.0)
                new_total = new_prompt_1m + new_comp_1m

                prev_pricing = {}
                if existing.details_json:
                    try:
                        prev_details = json.loads(existing.details_json)
                        prev_pricing = prev_details.get("pricing", {})
                    except Exception:
                        pass

                prev_prompt_1m = float(prev_pricing.get("prompt_1m", 0.0) or 0.0)
                prev_comp_1m = float(prev_pricing.get("completion_1m", 0.0) or 0.0)
                prev_total = prev_prompt_1m + prev_comp_1m

                # Detect price delta on non-zero rates
                if prev_total > 0 and new_total > 0 and abs(new_total - prev_total) > 0.0001:
                    pct_diff = round(((new_total - prev_total) / prev_total) * 100, 1)
                    if abs(pct_diff) >= 1.0:
                        existing.previous_price_prompt = prev_prompt_1m
                        existing.previous_price_completion = prev_comp_1m
                        existing.price_last_changed = now
                        existing.price_change_pct = pct_diff
                        existing.price_change_direction = "drop" if pct_diff < 0 else "hike"

                        changed_item = dict(m)
                        changed_item["price_change_pct"] = pct_diff
                        changed_item["price_change_direction"] = existing.price_change_direction
                        changed_item["prev_prompt_1m"] = prev_prompt_1m
                        changed_item["prev_completion_1m"] = prev_comp_1m
                        changed_item["new_prompt_1m"] = new_prompt_1m
                        changed_item["new_completion_1m"] = new_comp_1m
                        price_changed_models.append(changed_item)

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
    return {"new_models": new_models, "price_changed_models": price_changed_models}

async def get_recent_model_updates(limit: int = 50) -> Dict[str, Any]:
    """Retrieve recently added models and models with price changes."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DiscoveredModel))
        all_models = result.scalars().all()
        now = time.time()
        seven_days_ago = now - (7 * 86400)

        new_models = [
            {
                "id": m.id,
                "name": m.name,
                "brand": m.brand,
                "provider": m.provider,
                "tier": m.tier,
                "first_seen": m.first_seen,
                "popularity": m.popularity
            }
            for m in all_models if (m.first_seen and m.first_seen >= seven_days_ago)
        ]
        new_models.sort(key=lambda x: x["first_seen"], reverse=True)

        price_changes = [
            {
                "id": m.id,
                "name": m.name,
                "brand": m.brand,
                "provider": m.provider,
                "tier": m.tier,
                "price_last_changed": m.price_last_changed,
                "price_change_pct": m.price_change_pct,
                "price_change_direction": m.price_change_direction,
                "previous_price_prompt": m.previous_price_prompt,
                "previous_price_completion": m.previous_price_completion
            }
            for m in all_models if m.price_last_changed is not None
        ]
        price_changes.sort(key=lambda x: x["price_last_changed"] or 0, reverse=True)

        return {
            "status": "success",
            "recent_new": new_models[:limit],
            "price_changes": price_changes[:limit]
        }

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
