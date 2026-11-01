"""
Query route with Ollama integration and KV caching.
Simplified, production-ready implementation.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from backend.api.schemas.request import QueryRequest, QueryResponse, ErrorResponse
from backend.core.llm.ollama_client import context_builder, ollama_client
from backend.core.llm.cloud_llm_client import cloud_llm_client
from backend.validation.validator import sql_validator
from backend.execution.executor import sql_executor
from backend.monitoring.logger import correlation_id_ctx, get_logger, log_request_start

router = APIRouter()
logger = get_logger()

@router.post(
    "/query",
    response_model=QueryResponse,
    responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    tags=["Query"]
)
async def execute_query(request_body: QueryRequest):
    """
    Translates natural language text queries to PostgreSQL SELECT statements
    using Ollama with KV caching.
    """
    correlation_id = correlation_id_ctx.get()
    user_query = request_body.query
    
    log_request_start(
        method="POST",
        path="/api/query",
        correlation_id=correlation_id,
        query=user_query[:100]
    )
    
    logger.info(
        "Processing query",
        extra={"query_length": len(user_query), "correlation_id": correlation_id}
    )
    
    sql = ""
    stage = "initial"
    
    try:
        stage = f"{request_body.provider} SQL generation"
        if request_body.provider == "ollama":
            llm_result = await ollama_client.generate_sql(
                user_query=user_query,
                correlation_id=correlation_id
            )
        else:
            llm_result = await cloud_llm_client.generate_sql(
                user_query=user_query,
                provider=request_body.provider,
                correlation_id=correlation_id,
            )
        
        sql = llm_result["sql"]        
        logger.info(
            f"LLM generated SQL",
            extra={
                "sql": sql[:200],  # Truncate
                "correlation_id": correlation_id
            }
        )
        
        # ============================================
        # 2. SQL Validation
        # ============================================
        
        stage = "SQL validation"
        validation = sql_validator.validate(sql)
        
        if not validation["is_valid"]:
            error_msg = f"SQL Safety Violation: {validation['error']}"
            logger.warning(
                f"Generated SQL failed safety checks",
                extra={
                    "sql": sql,
                    "error": validation["error"],
                    "correlation_id": correlation_id
                }
            )
            
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "detail": error_msg,
                    "correlation_id": correlation_id
                }
            )
        
        safe_sql = validation["sql"]
        logger.info(
            "SQL validation passed",
            extra={
                "safe_sql": safe_sql[:200],
                "correlation_id": correlation_id
            }
        )
        
        # ============================================
        # 3. Execute SQL
        # ============================================
        
        stage = "SQL execution"
        execution_result = await sql_executor.execute(safe_sql, correlation_id)
        
        logger.info(
            "Query completed",
            extra={
                "row_count": execution_result["row_count"],
                "correlation_id": correlation_id
            }
        )
        
        return QueryResponse(
            sql=safe_sql,
            results=execution_result["rows"],
            row_count=execution_result["row_count"],
            correlation_id=correlation_id
        )
        
    except Exception as e:
        # ============================================
        # Error Handling
        # ============================================
        
        logger.error(
            f"Query processing failed during {stage}",
            extra={
                "error": str(e),
                "stage": stage,
                "correlation_id": correlation_id
            },
            exc_info=True
        )
        
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": f"Query processing failed during {stage}: {str(e)}",
                "correlation_id": correlation_id
            }
        )


# ============================================
# Cache Management Endpoints
# ============================================
@router.post("/cache/warmup", tags=["Cache"])
async def warmup_caches():
    """
    Pre-warm the shared schema context cache.
    This ensures low latency for first queries after deployment.
    """
    success = await ollama_client.warmup_cache()
    
    return {
        "status": "warmup_complete" if success else "warmup_failed",
        "keep_alive": ollama_client.config.keep_alive
    }


@router.post("/cache/invalidate", tags=["Cache"])
async def invalidate_cache():
    """
    Invalidate the combined static context.
    This forces a rebuild on the next query.
    """
    context_builder.invalidate()
    return {
        "status": "invalidated",
        "next_query": "will rebuild context from disk"
    }