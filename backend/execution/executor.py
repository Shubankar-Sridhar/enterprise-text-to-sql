from typing import Dict, Any
from backend.execution.connection_pool import db_pool
from backend.monitoring.logger import get_logger

logger = get_logger()

class SQLExecutor:
    """
    Handles query execution against the database connection pool,
    and database exceptions reporting.
    """
    async def execute(self, sql: str, correlation_id: str) -> Dict[str, Any]:
        """
        Executes raw SELECT queries and returns database rows and row counts.
        """
        logger.info(f"SQLExecutor: Executing validated SQL query. Correlation ID: {correlation_id}")
        
        try:
            # Execute query using connection pool read-only context
            rows = await db_pool.fetch(sql)
            logger.info(
                f"SQLExecutor: Returned {len(rows)} rows. Correlation ID: {correlation_id}"
            )
            
            return {
                "rows": rows,
                "row_count": len(rows)
            }
        except Exception as e:
            logger.error(
                f"SQLExecutor: Database execution failed - "
                f"Correlation ID: {correlation_id} - Error: {str(e)}"
            )
            raise

# Global SQL executor instance exporter
sql_executor = SQLExecutor()
