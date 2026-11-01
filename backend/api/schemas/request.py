from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal

class QueryRequest(BaseModel):
    """
    Schema for incoming natural language query requests.
    """
    query: str = Field(..., description="Natural language query to translate into SQL", min_length=1)
    provider: Literal["ollama", "openai", "gemini", "deepseek", "claude"] = Field(
        default="ollama",
        description="Inference provider for SQL generation; Ollama remains the default",
    )

class QueryResponse(BaseModel):
    """
    Response schema for query execution.
    """
    sql: str = Field(..., description="Generated, validated and executed SQL query")
    results: List[Dict[str, Any]] = Field(..., description="Database execution results")
    row_count: int = Field(..., description="Number of records returned by query")
    correlation_id: str = Field(..., description="Correlation ID for matching application logs")

class ErrorResponse(BaseModel):
    """
    Response schema for error details with correlation tracking.
    """
    detail: str = Field(..., description="Details of the error encountered")
    correlation_id: str = Field(..., description="Correlation ID for tracking downstream logs")

class HealthResponse(BaseModel):
    """
    Response schema for system health checks.
    """
    status: str = Field(..., description="Overall service status ('healthy' or 'unhealthy')")
    postgres: str = Field(..., description="Database connection status ('connected' or 'disconnected')")
