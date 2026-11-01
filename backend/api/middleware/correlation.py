import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from backend.monitoring.logger import correlation_id_ctx

class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates/extracts a correlation ID for every request,
    stores it in contextvars for logging, and adds it to response headers.
    """
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        token = correlation_id_ctx.set(correlation_id)
        
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_ctx.reset(token)
