import os
import re
import yaml
from sqlglot import parse, exp
from typing import Dict, Any, List, Optional
from backend.monitoring.logger import get_logger

logger = get_logger()

class SQLValidator:
    """
    SQL query validation engine. Uses both regex matching (as a fast defense-in-depth layer)
    and deep Abstract Syntax Tree (AST) validation using the `sqlglot` library to guarantee
    only read-only, safe, single-statement SELECT queries are executed.
    """
    _instance: Optional["SQLValidator"] = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance
        
    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
            
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.security_path = os.path.join(root_dir, "config", "security", "forbidden_patterns.yaml")
        logger.info(f"[+] SQL Validator: Security config path resolved to '{self.security_path}'")
        
        self.forbidden_keywords: List[str] = []
        self.forbidden_patterns: List[Dict[str, str]] = []
        self._load_config()
        self._initialized = True
        
    def _load_config(self) -> None:
        """
        Loads the forbidden keywords and regex pattern definitions from security configuration file.
        """
        try:
            if not os.path.exists(self.security_path):
                logger.warning(f"SQLValidator: Security config not found at '{self.security_path}'. Using default safety parameters.")
                # Load secure fallbacks
                self.forbidden_keywords = [
                    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", 
                    "TRUNCATE", "MERGE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK"
                ]
                self.forbidden_patterns = [
                    {"pattern": "';"},
                    {"pattern": r"OR\s+1\s*=\\s*1"},
                    {"pattern": r"UNION\s+SELECT"},
                    {"pattern": "--"},
                    {"pattern": r"/\*"}
                ]
                return
                
            with open(self.security_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self.forbidden_keywords = [kw.upper() for kw in data.get("forbidden_keywords", [])]
                self.forbidden_patterns = data.get("forbidden_patterns", [])
                
            logger.info("SQLValidator: Successfully loaded security check configurations.")
        except Exception as e:
            logger.error(f"SQLValidator: Failed to load security check configurations: {str(e)}")
            
    def validate(self, sql: str) -> Dict[str, Any]:
        """
        Validates SQL query, returns validation status, the cleaned/safe SQL query string, and any errors.
        """
        if not sql or not sql.strip():
            return {"is_valid": False, "sql": sql, "error": "Query string is empty"}
            
        # --- LAYER 1: Regex & Pattern Matching Checks ---
        cleaned_raw_sql = sql.strip()
        for item in self.forbidden_patterns:
            pattern = item.get("pattern", "")
            if pattern:
                try:
                    # Regex check with case insensitivity
                    if re.search(pattern, cleaned_raw_sql, re.IGNORECASE):
                        logger.warning(f"SQLValidator: Query rejected by pattern match: '{pattern}'")
                        return {
                            "is_valid": False,
                            "sql": sql,
                            "error": f"SQL security risk detected (pattern rule match: '{pattern}')"
                        }
                except Exception as e:
                    logger.error(f"SQLValidator: Regex error check matching '{pattern}': {str(e)}")
                    
        # --- LAYER 2: AST Parsability and Multi-statement Blockers ---
        try:
            # Parse query using PostgreSQL dialect rules
            statements = parse(cleaned_raw_sql, read="postgres")
            if not statements:
                return {"is_valid": False, "sql": sql, "error": "Failed to parse SQL content (empty AST)"}
            if len(statements) > 1:
                logger.warning(f"SQLValidator: Multi-statement query detected ({len(statements)} queries). Rejected.")
                return {"is_valid": False, "sql": sql, "error": "Multiple SQL statements in a single query are blocked"}
                
            statement = statements[0]
            if not statement:
                return {"is_valid": False, "sql": sql, "error": "Failed to parse SQL (invalid AST)"}
        except Exception as e:
            logger.warning(f"SQLValidator: Parse exception for SQL: '{sql}' - Error: {str(e)}")
            return {"is_valid": False, "sql": sql, "error": f"SQL syntax or dialect parsing error: {str(e)}"}
            
        # --- LAYER 3: AST Deep Node Inspection ---
        # Traverse every single node in the AST hierarchy
        for node in statement.walk():
            node_class = node.__class__.__name__
            
            # 1. Block modifications (Insert, Update, Delete, Alter, Create, Drop, Command, etc.)
            # sqlglot represents modifications as exp.Insert, exp.Delete, etc.
            if any(forbidden in node_class.upper() for forbidden in ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "COMMAND", "MERGE"]):
                logger.warning(f"SQLValidator: Query rejected. Prohibited node type: {node_class}")
                return {
                    "is_valid": False,
                    "sql": sql,
                    "error": f"DML or DDL operations not allowed (node type: {node_class})"
                }
                
            # 2. Block system catalogs references (pg_catalog, information_schema)
            if isinstance(node, exp.Table):
                table_name = node.name.lower()
                db_schema = node.args.get("db", "")
                db_schema_name = db_schema.name.lower() if db_schema else ""
                
                system_catalogs = ["pg_catalog", "information_schema", "pg_stat_activity", "pg_user", "pg_shadow"]
                if table_name in system_catalogs or db_schema_name in system_catalogs:
                    logger.warning(f"SQLValidator: Query references system catalog table '{table_name}' or schema '{db_schema_name}'")
                    return {
                        "is_valid": False,
                        "sql": sql,
                        "error": "Access to database system catalog information is blocked"
                    }
                    
            # 3. Block forbidden keywords inside raw identifiers
            if isinstance(node, exp.Identifier):
                identifier_name = node.name.upper()
                if identifier_name in self.forbidden_keywords:
                    logger.warning(f"SQLValidator: Forbidden identifier match: '{identifier_name}'")
                    return {
                        "is_valid": False,
                        "sql": sql,
                        "error": f"Prohibited SQL keyword detected: '{identifier_name}'"
                    }
                    
            # 4. Check for hazardous functions (e.g. pg_sleep, sleep)
            if isinstance(node, (exp.Anonymous, exp.Func)):
                func_name = node.name.lower() if hasattr(node, "name") else ""
                if "pg_" in func_name or "sleep" in func_name:
                    logger.warning(f"SQLValidator: Prohibited function usage: '{func_name}'")
                    return {
                        "is_valid": False,
                        "sql": sql,
                        "error": f"Execution of dangerous database functions is blocked ('{func_name}')"
                    }
                    
        # --- LAYER 4: Root Node Read-Only Constraints ---
        # The top-level query operation must be SELECT or UNION (which is fundamentally a query combining SELECTs)
        if not isinstance(statement, (exp.Select, exp.Union)):
            logger.warning(f"SQLValidator: Root query node is not Select/Union: {statement.__class__.__name__}")
            return {
                "is_valid": False,
                "sql": sql,
                "error": "Only standard queries (SELECT) are authorized for execution"
            }
            
        # --- LAYER 5: Limit Rule Injection ---
        # Inject standard LIMIT constraints if they are omitted by the generator
        if isinstance(statement, exp.Select):
            if not statement.args.get("limit"):
                statement = statement.limit(1000)
                logger.info("SQLValidator: No LIMIT clause found. Auto-injected LIMIT 1000.")
        elif isinstance(statement, exp.Union):
            if not statement.args.get("limit"):
                statement = statement.limit(1000)
                logger.info("SQLValidator: Union query has no LIMIT. Auto-injected LIMIT 1000.")
                
        # Generate safe SQL representation back from AST
        safe_sql = statement.sql(dialect="postgres")
        
        return {
            "is_valid": True,
            "sql": safe_sql,
            "error": None
        }

# Global SQL validator instance exporter
sql_validator = SQLValidator()
