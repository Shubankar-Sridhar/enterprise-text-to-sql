import time
from collections import defaultdict
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.monitoring.logger import get_logger

logger = get_logger()

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory sliding window rate limiter.
    Limits requests per minute (default 100) per client (API key hash or IP address).
    Bypasses health and documentation routes.
    """
    def __init__(self, app):
        super().__init__(app)
        self.request_history = defaultdict(list)
        
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        bypass_paths = [
            "/api/health",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        if any(path == p or path.startswith(p + "/") for p in bypass_paths):
            return await call_next(request)
            
        client_id = getattr(request.state, "api_key_hash", None)
        if not client_id:
            client_id = request.client.host if request.client else "unknown_ip"
            
        limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
        now = time.time()
        window_seconds = 60.0
        
        history = self.request_history[client_id]
        while history and history[0] < now - window_seconds:
            history.pop(0)
            
        remaining = limit - len(history)
        
        if remaining <= 0:
            retry_after = int(window_seconds - (now - history[0])) if history else int(window_seconds)
            logger.warning(f"Rate limit exceeded for client: {client_id}. Limit: {limit}")
            
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            return response
        
        history.append(now)
        
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
        
        return response
