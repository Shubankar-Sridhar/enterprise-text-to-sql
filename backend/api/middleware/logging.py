from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from backend.monitoring.logger import get_logger

logger = get_logger()

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log details of incoming requests and outgoing responses,
    including status code and exception handling.
    """
    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown_ip"
        logger.info(
            f"Request started: {method} {path}",
            extra={
                "request_method": method,
                "request_path": path,
                "client_ip": client_ip
            }
        )
        
        try:
            response = await call_next(request)
            logger.info(
                f"Request completed: {method} {path} - Status: {response.status_code}",
                extra={
                    "request_method": method,
                    "request_path": path,
                    "client_ip": client_ip,
                    "response_status": response.status_code
                }
            )
            return response
        except Exception as e:
            logger.error(
                f"Request failed: {method} {path} - Error: {str(e)}",
                exc_info=True,
                extra={
                    "request_method": method,
                    "request_path": path,
                    "client_ip": client_ip
                }
            )
            raise
