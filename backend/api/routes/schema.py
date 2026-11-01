from fastapi import APIRouter
from backend.core.schema.loader import schema_loader

router = APIRouter()


@router.get("/schema", tags=["Schema"])
async def get_schema():
    """
    Returns the full database schema structure including all table and column definitions.
    """
    schema = await schema_loader.get_schema()
    return schema
