import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routes import rules, webhook, stats, health
from app.services.dm_worker import dm_worker
from app.services.reconciler import reconciler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: Initialize DB schema & start background tasks
    await init_db()
    
    worker_task = asyncio.create_task(dm_worker.start())
    reconciler_task = asyncio.create_task(reconciler.start())
    
    yield
    
    # Shutdown logic: Gracefully stop background workers
    await dm_worker.stop()
    await reconciler.stop()
    worker_task.cancel()
    reconciler_task.cancel()

app = FastAPI(
    title="LinkPlease Instagram DM Automation API",
    description="Hostile API resilient Instagram DM automation microservice",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(rules.router)
app.include_router(webhook.router)
app.include_router(stats.router)
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
