from fastapi import APIRouter, Response, status
from backend.api.schemas.request import HealthResponse
from backend.execution.connection_pool import db_pool

router = APIRouter()

async def get_health_status() -> dict:
    postgres_status = "disconnected"
    try:
        postgres_status = "connected" if await db_pool.is_connected() else "disconnected"
    except Exception:
        postgres_status = "disconnected"

    status_str = "healthy" if postgres_status == "connected" else "unhealthy"

    return {
        "status": status_str,
        "postgres": postgres_status
    }

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Get comprehensive health status of the application backend, including
    PostgreSQL connectivity.
    """
    return await get_health_status()

@router.head("/health", tags=["Health"])
async def health_check_head(response: Response):
    """
    Head request check for load balancers. Returns 200 if healthy, 503 if unhealthy.
    """
    health = await get_health_status()
    if health.status != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK
    return response
