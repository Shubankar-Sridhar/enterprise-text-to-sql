import json
import os
from typing import Any, Dict, List, Optional

from backend.core.config import config_lock
from backend.monitoring.logger import get_logger

logger = get_logger()


class SchemaLoader:
    """
    Thread-safe and asyncio-safe loader for the JSON database schema.
    """

    _instance: Optional["SchemaLoader"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return

        root_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        )
        self.schema_path = os.path.join(root_dir, "config", "schema.json")
        self._schema: Dict[str, Any] = {}
        self._schema_text: str = ""
        self._initialized = True

    def load_sync(self) -> None:
        """Load and normalize the configured JSON schema."""
        logger.info(f"[+] Schema Loader: Schema file resolved to '{self.schema_path}'")
        try:
            with open(self.schema_path, "r", encoding="utf-8") as schema_file:
                source_schema = json.load(schema_file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"Error loading SQL schema configuration: {exc}")
            return

        schemas = source_schema.get("schemas")
        if not isinstance(schemas, list):
            logger.error(
                f"Invalid schema configuration in '{self.schema_path}': "
                "expected a 'schemas' list."
            )
            return

        tables: List[Dict[str, Any]] = []
        for schema_entry in schemas:
            if not isinstance(schema_entry, dict):
                logger.error(
                    f"Invalid schema configuration in '{self.schema_path}': "
                    "each schema entry must be an object."
                )
                return

            schema_name = schema_entry.get("name", "")
            schema_tables = schema_entry.get("tables", [])
            if not isinstance(schema_tables, list):
                logger.error(
                    f"Invalid schema configuration in '{self.schema_path}': "
                    f"tables for schema '{schema_name}' must be a list."
                )
                return

            for table in schema_tables:
                if not isinstance(table, dict) or not isinstance(
                    table.get("columns", []), list
                ):
                    logger.error(
                        f"Invalid schema configuration in '{self.schema_path}': "
                        f"invalid table in schema '{schema_name}'."
                    )
                    return
                tables.append(self._normalize_table(table, schema_name))

        database = source_schema.get("database", {})
        database_name = (
            database.get("type", "Unknown Database")
            if isinstance(database, dict)
            else "Unknown Database"
        )
        self._schema = {"database_name": database_name, "tables": tables}
        self._schema_text = self._build_schema_text()
        logger.info("Successfully loaded and parsed JSON schema configuration.")

    @staticmethod
    def _normalize_table(table: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        table_schema = table.get("schema") or schema_name
        table_name = table.get("name", "")
        foreign_keys = table.get("foreign_keys", [])
        foreign_key_by_column: Dict[str, str] = {}
        if isinstance(foreign_keys, list):
            for foreign_key in foreign_keys:
                if not isinstance(foreign_key, dict):
                    continue
                referred_schema = foreign_key.get("referred_schema")
                referred_table = foreign_key.get("referred_table", "")
                referred_columns = foreign_key.get("referred_columns", [])
                target = ".".join(
                    part
                    for part in (
                        referred_schema,
                        referred_table,
                        ", ".join(referred_columns)
                        if isinstance(referred_columns, list)
                        else "",
                    )
                    if part
                )
                constrained_columns = foreign_key.get("constrained_columns", [])
                if isinstance(constrained_columns, list):
                    for column_name in constrained_columns:
                        if isinstance(column_name, str):
                            foreign_key_by_column[column_name] = target

        primary_keys = table.get("primary_keys", [])
        primary_key_names = set(primary_keys) if isinstance(primary_keys, list) else set()
        columns = []
        for column in table.get("columns", []):
            if not isinstance(column, dict):
                continue
            column_name = column.get("name", "")
            columns.append(
                {
                    "name": column_name,
                    "data_type": column.get("type", column.get("data_type", "")),
                    "primary_key": column.get(
                        "primary_key", column_name in primary_key_names
                    ),
                    "nullable": column.get("nullable", True),
                    "description": column.get("comment") or "",
                    "foreign_key": foreign_key_by_column.get(column_name, ""),
                }
            )

        return {
            "name": table_name,
            "schema": table_schema,
            "description": table.get("description", ""),
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
            "indexes": table.get("indexes", []),
        }

    def _build_schema_text(self) -> str:
        """Generate the schema description used in LLM prompt context."""
        if not self._schema:
            return ""
        lines = [f"Database Name: {self._schema.get('database_name', 'Unknown DB')}"]
        for table in self._schema.get("tables", []):
            table_name = table.get("name", "")
            schema_name = table.get("schema")
            qualified_name = (
                f"{schema_name}.{table_name}" if schema_name else table_name
            )
            lines.extend(
                [
                    f"\nTable: {qualified_name}",
                    f"Description: {table.get('description', '')}",
                    "Columns:",
                ]
            )
            for column in table.get("columns", []):
                primary_key = " (Primary Key)" if column.get("primary_key") else ""
                foreign_key = (
                    f" (Foreign Key referencing {column['foreign_key']})"
                    if column.get("foreign_key")
                    else ""
                )
                nullable = (
                    " (Nullable)" if column.get("nullable") else " (Not Null)"
                )
                lines.append(
                    f"  - {column.get('name')} {column.get('data_type')}"
                    f"{primary_key}{foreign_key}{nullable}: "
                    f"{column.get('description', '')}"
                )
        return "\n".join(lines)

    async def get_schema(self) -> Dict[str, Any]:
        """Get the loaded schema dictionary, loading it on first access."""
        async with config_lock:
            if not self._schema:
                self.load_sync()
            return self._schema

    async def get_schema_text(self) -> str:
        """Get the text-based description of the database schema."""
        async with config_lock:
            if not self._schema_text:
                self.load_sync()
            logger.info("Providing combined schema text.")
            return self._schema_text

    async def get_tables(self) -> List[str]:
        """Get table names from the loaded schema."""
        schema = await self.get_schema()
        return [table.get("name") for table in schema.get("tables", [])]

    async def get_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Get column details for a table."""
        schema = await self.get_schema()
        for table in schema.get("tables", []):
            if table.get("name") == table_name:
                return table.get("columns", [])
        return []


schema_loader = SchemaLoader()
