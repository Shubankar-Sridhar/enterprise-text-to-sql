"""
NL2SQL Enterprise Backend - Local Model Edition
Uses Ollama for SQL generation with KV caching.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

load_dotenv()

# Import enterprise logging first
from backend.monitoring.logger import setup_logger

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logger = setup_logger(log_level)

# Import components
from backend.execution.connection_pool import db_pool
from backend.core.llm.ollama_client import initialize_ollama

# Import routes
from backend.api.routes.health import router as health_router
from backend.api.routes.query import router as query_router
from backend.api.routes.schema import router as schema_router
from backend.api.routes.admin import router as admin_router

# Import middleware
from backend.api.middleware.correlation import CorrelationMiddleware
from backend.api.middleware.logging import LoggingMiddleware
from backend.api.middleware.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Server lifespan context manager for initialization and cleanup.
    """
    logger.info("Initializing NL2SQL Enterprise Backend (Local Model Edition)...")
    
    try:
        # Initialize core services
        await db_pool.initialize()
        
        # Initialize Ollama and build caches
        await initialize_ollama()
        
        logger.info("NL2SQL Enterprise Backend successfully booted and ready.")
        
    except Exception as e:
        logger.error(f"Failed to initialize system: {e}", exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Tearing down NL2SQL Enterprise Backend system services...")
    await db_pool.close()
    logger.info("Cleanup completed. Backend offline.")


app = FastAPI(
    title="NL2SQL Enterprise API (Local Model Edition)",
    description="Natural Language to SQL conversion using Ollama with KV caching",
    version="2.0.0",
    lifespan=lifespan
)

# CORS configuration
cors_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware
app.add_middleware(RateLimitMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(CorrelationMiddleware)

# Routes
app.include_router(health_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(schema_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "service": "NL2SQL Enterprise (Local Model Edition)",
        "version": "2.0.0",
        "status": "operational",
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
        "cache_engine": "ollama_kv_cache"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=os.getenv("DEV_MODE", "false").lower() == "true"
    )