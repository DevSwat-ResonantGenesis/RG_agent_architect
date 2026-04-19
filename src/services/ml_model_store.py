"""ML Model Store — PostgreSQL persistence for trained classifier models.

Stores pickled model blobs + stats + active learning samples in the
managed external database so they survive container rebuilds/restarts.

Table: ml_models
  - model_name (PK): e.g. "prompt_classifier", "agent_type_classifier"
  - model_data (bytea): pickled classifier blob
  - stats (jsonb): accuracy, n_samples, per-class metrics
  - updated_at (timestamp)

Table: ml_active_samples
  - id (serial PK)
  - model_name: which classifier this sample belongs to
  - sample_data (jsonb): {message, predicted_modules/type, confidence}
  - created_at (timestamp)
"""
import asyncio
import logging
import os
import pickle
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Convert asyncpg URL to psycopg2-compatible for sync operations
def _get_sync_url() -> str:
    url = DATABASE_URL
    if not url:
        return ""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _get_async_url() -> str:
    url = DATABASE_URL
    if not url:
        return ""
    # Ensure asyncpg driver
    if "asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


# ── Async DB engine (lazy init) ──

_engine = None
_sessionmaker = None


async def _get_session():
    global _engine, _sessionmaker
    if _engine is None:
        url = _get_async_url()
        if not url:
            raise RuntimeError("DATABASE_URL not configured")
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker

        connect_args = {}
        if "ssl=require" in url or "sslmode=require" in url:
            import ssl as _ssl
            ssl_ctx = _ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = _ssl.CERT_NONE
            connect_args["ssl"] = ssl_ctx

        _engine = create_async_engine(
            url.split("?")[0] + "?ssl=require" if "ssl" not in url else url,
            pool_size=3,
            max_overflow=2,
            pool_timeout=10,
            connect_args=connect_args,
        )
        _sessionmaker = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _sessionmaker()


async def ensure_tables() -> bool:
    """Create ml_models + ml_active_samples tables if they don't exist."""
    try:
        session = await _get_session()
        async with session:
            await session.execute(
                __import__("sqlalchemy").text("""
                    CREATE TABLE IF NOT EXISTS ml_models (
                        model_name VARCHAR(128) PRIMARY KEY,
                        model_data BYTEA,
                        stats JSONB DEFAULT '{}',
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
            )
            await session.execute(
                __import__("sqlalchemy").text("""
                    CREATE TABLE IF NOT EXISTS ml_active_samples (
                        id SERIAL PRIMARY KEY,
                        model_name VARCHAR(128) NOT NULL,
                        sample_data JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
            )
            await session.execute(
                __import__("sqlalchemy").text("""
                    CREATE INDEX IF NOT EXISTS idx_ml_active_samples_model
                    ON ml_active_samples(model_name)
                """)
            )
            await session.commit()
        logger.info("[MLModelStore] Tables ensured (ml_models, ml_active_samples)")
        return True
    except Exception as e:
        logger.error(f"[MLModelStore] Table creation failed: {e}")
        return False


async def save_model(model_name: str, model_obj: Any, stats: Dict) -> bool:
    """Save a trained model (pickle blob) + stats to DB."""
    try:
        blob = pickle.dumps(model_obj)
        session = await _get_session()
        from sqlalchemy import text
        async with session:
            await session.execute(
                text("""
                    INSERT INTO ml_models (model_name, model_data, stats, updated_at)
                    VALUES (:name, :data, :stats, NOW())
                    ON CONFLICT (model_name)
                    DO UPDATE SET model_data = :data, stats = :stats, updated_at = NOW()
                """),
                {"name": model_name, "data": blob, "stats": __import__("json").dumps(stats)},
            )
            await session.commit()
        logger.info(f"[MLModelStore] Saved model '{model_name}' ({len(blob)} bytes)")
        return True
    except Exception as e:
        logger.error(f"[MLModelStore] save_model failed for '{model_name}': {e}")
        return False


async def load_model(model_name: str) -> Optional[Dict]:
    """Load a model from DB. Returns {"model": unpickled_obj, "stats": dict} or None."""
    try:
        session = await _get_session()
        from sqlalchemy import text
        async with session:
            result = await session.execute(
                text("SELECT model_data, stats FROM ml_models WHERE model_name = :name"),
                {"name": model_name},
            )
            row = result.fetchone()
        if not row or not row[0]:
            return None
        model_obj = pickle.loads(row[0])
        stats = row[1] if isinstance(row[1], dict) else __import__("json").loads(row[1] or "{}")
        logger.info(f"[MLModelStore] Loaded model '{model_name}' from DB")
        return {"model": model_obj, "stats": stats}
    except Exception as e:
        logger.error(f"[MLModelStore] load_model failed for '{model_name}': {e}")
        return None


async def save_active_samples(model_name: str, samples: List[Dict]) -> bool:
    """Batch-insert active learning samples."""
    if not samples:
        return True
    try:
        session = await _get_session()
        from sqlalchemy import text
        import json
        async with session:
            for sample in samples:
                await session.execute(
                    text("""
                        INSERT INTO ml_active_samples (model_name, sample_data, created_at)
                        VALUES (:name, :data, NOW())
                    """),
                    {"name": model_name, "data": json.dumps(sample)},
                )
            await session.commit()
        logger.info(f"[MLModelStore] Saved {len(samples)} active samples for '{model_name}'")
        return True
    except Exception as e:
        logger.error(f"[MLModelStore] save_active_samples failed: {e}")
        return False


async def load_active_samples(model_name: str, min_confidence: float = 0.5) -> List[Dict]:
    """Load all active learning samples for a model above confidence threshold."""
    try:
        session = await _get_session()
        from sqlalchemy import text
        async with session:
            result = await session.execute(
                text("""
                    SELECT sample_data FROM ml_active_samples
                    WHERE model_name = :name
                    ORDER BY created_at
                """),
                {"name": model_name},
            )
            rows = result.fetchall()
        samples = []
        for row in rows:
            data = row[0] if isinstance(row[0], dict) else __import__("json").loads(row[0] or "{}")
            if data.get("confidence", 0) >= min_confidence:
                samples.append(data)
        logger.info(f"[MLModelStore] Loaded {len(samples)} active samples for '{model_name}'")
        return samples
    except Exception as e:
        logger.error(f"[MLModelStore] load_active_samples failed: {e}")
        return []


def is_available() -> bool:
    """Check if DATABASE_URL is configured."""
    return bool(DATABASE_URL)
