import os
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from backend.core.llm.ollama_client import ollama_client, context_builder
from backend.monitoring.logger import get_logger

router = APIRouter()
logger = get_logger()

@router.post("/admin/cache/refresh", tags=["Admin"])
async def force_cache_refresh():
    """
    Rebuilds the shared static context and warms up the Ollama KV cache.
    """
    logger.info("AdminRoute: Force cache refresh initiated.")
    try:
        context_builder.invalidate()
        await context_builder.get_or_build_context()
        cache_warmed = await ollama_client.warmup_cache()
        return {
            "message": "Ollama KV cache successfully refreshed.",
            "context_refreshed": True,
            "cache_warmed": cache_warmed,
        }
    except Exception as e:
        logger.error(f"AdminRoute: Cache refresh failed: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Cache refresh failed: {str(e)}"}
        )


@router.post("/admin/cache/clear", tags=["Admin"])
async def clear_cache():
    """
    Completely clears the Ollama KV cache and static contexts.
    The next query will trigger a fresh cache build cycle.
    """
    logger.info("AdminRoute: Cache clear initiated.")
    try:
        context_builder.invalidate()
        cache_warmed = None
        if os.getenv("OLLAMA_AUTO_WARMUP", "true").lower() == "true":
            cache_warmed = await ollama_client.warmup_cache()
        
        return {
            "message": "Combined Ollama context cache cleared.",
            "cache_warmed": cache_warmed,
        }
    except Exception as e:
        logger.error(f"AdminRoute: Cache clear failed: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Cache clear failed: {str(e)}"}
        )


@router.post("/admin/cache/warmup", tags=["Admin"])
async def warmup_cache():
    """
    Warms up the Ollama KV cache for the combined schema context.
    """
    try:
        success = await ollama_client.warmup_cache()
        return {
            "message": "Cache warmup completed." if success else "Cache warmup failed.",
            "cache_warmed": success,
        }
    except Exception as e:
        logger.error(f"AdminRoute: Cache warmup failed: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Cache warmup failed: {str(e)}"}
        )