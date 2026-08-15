import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.config import settings

logger = logging.getLogger("database")

def get_normalized_database_url() -> str:
    url = settings.DATABASE_URL
    if not url:
        return "sqlite+aiosqlite:///./linkplease.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

db_url = get_normalized_database_url()
is_sqlite = "sqlite" in db_url

# Configure engine based on dialect
if is_sqlite:
    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={"timeout": 30.0}
    )
    
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()
else:
    # PostgreSQL async connection with connection pooling
    engine = create_async_engine(
        db_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True
    )

# Session factory for DB operations
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    masked_url = db_url.split("@")[-1] if "@" in db_url else db_url
    dialect_name = "sqlite" if is_sqlite else "postgresql"
    logger.info(f"⚡ DB INITIALIZED: Active Backend Dialect -> [{dialect_name.upper()}] (Host/Target: {masked_url})")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Initialize StatCounter row 1 if not exists
    from app.models import StatCounter
    async with AsyncSessionLocal() as session:
        stat = await session.get(StatCounter, 1)
        if not stat:
            session.add(StatCounter(id=1, sent=0, failed=0, queued=0, duplicates_blocked=0))
            await session.commit()
