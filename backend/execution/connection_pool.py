import os
import asyncpg
from typing import Optional, List, Dict, Any
from backend.monitoring.logger import get_logger

logger = get_logger()

DATABASE_SEARCH_PATH = "public"

class DatabaseConnectionPool:
    _instance: Optional["DatabaseConnectionPool"] = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance
        
    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = True
        
    async def initialize(self) -> None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("ConnectionPool: DATABASE_URL environment variable is missing.")
            return
            
        min_size = int(os.getenv("DB_POOL_MIN_SIZE", "5"))
        max_size = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
        
        try:
            self.pool = await asyncpg.create_pool(
                host=os.getenv("DATABASE_HOST"),
                port=int(os.getenv("DATABASE_PORT", "5432")),
                user=os.getenv("DATABASE_USER"),
                password=os.getenv("DATABASE_PASSWORD"),
                database=os.getenv("DATABASE_NAME"),
                server_settings={"search_path": DATABASE_SEARCH_PATH},
                min_size=min_size,
                max_size=max_size,
                command_timeout=float(os.getenv("QUERY_TIMEOUT_SECONDS", "30.0"))
            )
            logger.info("ConnectionPool: Successfully initialized PostgreSQL connection pool.")
        except Exception as e:
            logger.error(f"ConnectionPool: Failed to initialize PostgreSQL pool: {str(e)}")
            self.pool = None
            
    async def is_connected(self) -> bool:
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.warning(f"ConnectionPool: Pool connection check failed: {str(e)}")
            return False
            
    async def close(self) -> None:
        if self.pool:
            try:
                await self.pool.close()
                logger.info("ConnectionPool: Closed PostgreSQL connection pool.")
            except Exception as e:
                logger.error(f"ConnectionPool: Error closing pool: {str(e)}")
            finally:
                self.pool = None
                
    async def fetch(self, sql: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.pool:
            raise RuntimeError("PostgreSQL Connection Pool is not initialized")
            
        timeout = float(os.getenv("QUERY_TIMEOUT_SECONDS", "30.0"))
        
        async with self.pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                records = await conn.fetch(sql, timeout=timeout)
                max_rows = limit or int(os.getenv("MAX_RESULT_ROWS", "10000"))
                sliced_records = records[:max_rows]
                return [dict(record) for record in sliced_records]

db_pool = DatabaseConnectionPool()
