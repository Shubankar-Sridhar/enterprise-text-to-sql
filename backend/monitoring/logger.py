"""Backward-compatible imports for application logging."""

from backend.monitoring.structured_logging import (
    setup_logger,
    get_logger,
    correlation_id_ctx,
    LogContext,
    log_structured,
    log_request_start,
    CorrelationIdFilter,
)

__all__ = [
    'get_logger',
    'setup_logger',
    'correlation_id_ctx',
    'LogContext',
    'log_structured',
    'log_request_start',
    'CorrelationIdFilter',
]

def get_module_logger():
    """Get the module-level logger for backward compatibility."""
    return get_logger()

logger = get_module_logger()