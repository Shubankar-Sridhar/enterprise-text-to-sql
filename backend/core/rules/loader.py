import json
import os
from typing import Any, Dict, Optional

from backend.core.config import config_lock
from backend.monitoring.logger import get_logger

logger = get_logger()


class RulesLoader:
    """
    Thread-safe and asyncio-safe loader for the JSON business rules.
    Shares the config_lock with SchemaLoader to serialize configuration access.
    """

    _instance: Optional["RulesLoader"] = None

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
        self.rules_path = os.path.join(root_dir, "config", "business_rules.json")
        self._rules: Dict[str, Any] = {}
        self._rules_text: str = ""
        self._initialized = True

    def load_sync(self) -> None:
        """Load the configured JSON business rules."""
        try:
            with open(self.rules_path, "r", encoding="utf-8") as rules_file:
                rules = json.load(rules_file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"Error loading business rules configuration: {exc}")
            return

        if not isinstance(rules, dict):
            logger.error(
                f"Invalid business rules configuration in '{self.rules_path}': "
                "expected a JSON object."
            )
            return

        self._rules = rules
        self._rules_text = self._build_rules_text()
        logger.info("Successfully loaded business_rules.json configuration.")

    def _build_rules_text(self) -> str:
        """Format business rules and terminology for LLM prompt context."""
        if not self._rules:
            return ""

        lines = ["Business Rules and Mappings:"]
        rule_definitions = self._rules.get("rules", {})
        if isinstance(rule_definitions, dict) and rule_definitions:
            lines.append("\nBusiness Rules:")
            for name, rule in rule_definitions.items():
                if isinstance(rule, dict):
                    definition = rule.get("definition", "")
                    lines.append(f"  - {name}: {definition}")
                    for key in ("conditions", "inclusions", "exclusions"):
                        values = rule.get(key, [])
                        if values:
                            lines.append(f"      {key.title()}: {', '.join(values)}")
                else:
                    lines.append(f"  - {name}: {rule}")

        terminology = self._rules.get("terminology", {})
        if isinstance(terminology, dict) and terminology:
            lines.append("\nTerminology Mappings:")
            for term, details in terminology.items():
                if isinstance(details, dict):
                    meaning = details.get("meaning", "")
                    synonyms = details.get("synonyms", [])
                    suffix = f" (synonyms: {', '.join(synonyms)})" if synonyms else ""
                    lines.append(f"  - {term}: {meaning}{suffix}")
                else:
                    lines.append(f"  - {term}: {details}")

        for key, value in self._rules.items():
            if key not in {"rules", "terminology"}:
                lines.append(f"\n{key.replace('_', ' ').title()}: {value}")

        return "\n".join(lines)

    async def get_rules_text(self) -> str:
        """Get the formatted business rules, loading them on first access."""
        async with config_lock:
            if not self._rules_text:
                self.load_sync()
            return self._rules_text


rules_loader = RulesLoader()
