"""Structured JSON logging configuration and helpers."""

import logging
import os
import sys
from typing import Any, Dict
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdFilter(logging.Filter):
    """Inject correlation_id into every log record."""
    
    def filter(self, record):
        record.correlation_id = correlation_id_ctx.get()
        record.service_name = os.getenv("SERVICE_NAME", "nl2sql-backend")
        record.environment = os.getenv("ENVIRONMENT", "production")
        record.hostname = os.getenv("HOSTNAME", "unknown")
        return True


class StructuredJsonFormatter(jsonlogger.JsonFormatter):
    """
    Structured JSON formatter for ELK/Datadog compatibility.
    Includes all necessary fields for observability.
    """
    
    def __init__(self):
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s %(service_name)s %(environment)s",
            rename_fields={
                "asctime": "@timestamp",
                "levelname": "severity",
                "name": "logger_name",
            }
        )
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]):
        """Add extra fields to the log record."""
        super().add_fields(log_record, record, message_dict)
        
        # Add always-present fields
        log_record["correlation_id"] = correlation_id_ctx.get()
        log_record["service_name"] = os.getenv("SERVICE_NAME", "nl2sql-backend")
        log_record["environment"] = os.getenv("ENVIRONMENT", "production")
        log_record["hostname"] = os.getenv("HOSTNAME", "unknown")
        
def setup_logger(level: str = "INFO") -> logging.Logger:
    """
    Configure the application logger with:
    - Structured JSON output for ELK/Datadog
    - Correlation ID injection
    - File handlers for persistent local logs
    """
    logger_name = "nl2sql"
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console Handler (JSON for production)
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = StructuredJsonFormatter()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler (JSON for persistence)
    log_dir = os.getenv("LOG_DIR", "/app/logs")
    
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "nl2sql.json.log")
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # File Handler for Errors (separate)
    error_file = os.path.join(log_dir, "nl2sql.error.json.log")
    error_handler = logging.FileHandler(error_file, mode="a", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # Add correlation filter
    logger.addFilter(CorrelationIdFilter())
    
    logger.info(f"Structured logger initialized. Log level: {level}")
    logger.info(f"Log files: {log_file}, {error_file}")
    
    return logger


def get_logger() -> logging.Logger:
    """Get the configured application logger."""
    logger = logging.getLogger("nl2sql")
    if not logger.handlers:
        setup_logger()
    return logger


class LogContext:
    """Context manager for structured logging with extra fields."""
    
    def __init__(self, **kwargs):
        self.extra = kwargs
        self.logger = get_logger()
    
    def __enter__(self):
        self.original_extra = getattr(self.logger, '_extra', {})
        self.logger._extra = {**self.original_extra, **self.extra}
        return self.logger
    
    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.logger._extra = self.original_extra


def log_structured(level: str, message: str, **kwargs):
    """Log a structured message with extra fields."""
    logger = get_logger()
    getattr(logger, level)(message, extra=kwargs)


def log_request_start(method: str, path: str, correlation_id: str, **kwargs):
    """Log the start of a request with structured fields."""
    log_structured(
        "info",
        f"Request started: {method} {path}",
        request_method=method,
        request_path=path,
        correlation_id=correlation_id,
        event_type="request_start",
        **kwargs
    )


__all__ = [
    'setup_logger',
    'get_logger',
    'correlation_id_ctx',
    'CorrelationIdFilter',
    'LogContext',
    'log_structured',
    'log_request_start',
]