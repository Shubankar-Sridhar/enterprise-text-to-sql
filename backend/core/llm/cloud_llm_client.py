"""Cloud-provider adapters for natural-language SQL generation."""

import json
import os
import re
from datetime import datetime
from typing import Literal

from backend.core.llm.ollama_client import context_builder
from backend.monitoring.logger import get_logger

CloudProvider = Literal["openai", "gemini", "deepseek", "claude"]

logger = get_logger()


class CloudLLMClient:
    """Generate SQL with supported hosted providers, without local KV caching."""

    @property
    def temperature(self) -> float:
        try:
            return float(os.getenv("CLOUD_LLM_TEMPERATURE", "0.1"))
        except ValueError as error:
            raise RuntimeError("CLOUD_LLM_TEMPERATURE must be numeric.") from error

    @property
    def max_tokens(self) -> int:
        try:
            return int(os.getenv("CLOUD_LLM_MAX_TOKENS", "2048"))
        except ValueError as error:
            raise RuntimeError("CLOUD_LLM_MAX_TOKENS must be an integer.") from error

    async def generate_sql(
        self,
        user_query: str,
        provider: CloudProvider,
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        prompt = await self._build_prompt(user_query)
        try:
            if provider in ("openai", "deepseek"):
                response_text = await self._generate_openai_compatible(prompt, provider)
            elif provider == "gemini":
                response_text = await self._generate_gemini(prompt)
            elif provider == "claude":
                response_text = await self._generate_claude(prompt)
            else:
                raise ValueError(f"Unsupported cloud LLM provider: {provider}")
            return {"sql": self._parse_sql(response_text)}
        except Exception:
            logger.exception(
                "Cloud LLM SQL generation failed",
                extra={"provider": provider, "correlation_id": correlation_id},
            )
            raise

    async def _build_prompt(self, user_query: str) -> str:
        context = await context_builder.get_or_build_context()
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""{context}

### RUNTIME CONTEXT
Current timestamp: {current_timestamp}
Use this literal value for any date/time comparisons.
- For "today": use '{current_timestamp.split()[0]}'
- For "this month": use '{current_timestamp[:7]}'
- For "this year": use '{current_timestamp[:4]}'

### USER QUERY
{user_query}

### RESPONSE (JSON)
"""

    async def _generate_openai_compatible(
        self,
        prompt: str,
        provider: Literal["openai", "deepseek"],
    ) -> str:
        from openai import AsyncOpenAI

        if provider == "openai":
            api_key_env = "OPENAI_API_KEY"
            model_env = "OPENAI_MODEL"
            default_model = "gpt-4o-mini"
            base_url = None
        else:
            api_key_env = "DEEPSEEK_API_KEY"
            model_env = "DEEPSEEK_MODEL"
            default_model = "deepseek-chat"
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"{api_key_env} must be set to use {provider}.")

        model = os.getenv(model_env) or default_model
        client_options = {"api_key": api_key}
        if base_url:
            client_options["base_url"] = base_url

        async with AsyncOpenAI(**client_options) as client:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        if not response.choices or not response.choices[0].message.content:
            raise RuntimeError(f"{provider} returned no SQL-generation content.")
        return response.choices[0].message.content

    async def _generate_gemini(self, prompt: str) -> str:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY must be set to use Gemini.")

        model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
            ),
        )

        if not response.text:
            raise RuntimeError("Gemini returned no SQL-generation content.")
        return response.text

    async def _generate_claude(self, prompt: str) -> str:
        from anthropic import AsyncAnthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set to use Claude.")

        model = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5-20250929"
        async with AsyncAnthropic(api_key=api_key) as client:
            response = await client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )

        text = "\n".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        if not text:
            raise RuntimeError("Claude returned no SQL-generation content.")
        return text

    @staticmethod
    def _parse_sql(response_text: str) -> str:
        cleaned_text = re.sub(r"```(?:json)?\s*", "", response_text, flags=re.IGNORECASE)
        cleaned_text = re.sub(r"\s*```$", "", cleaned_text).strip()

        try:
            response_data = json.loads(cleaned_text)
        except json.JSONDecodeError:
            response_data = None

        if isinstance(response_data, dict):
            sql = response_data.get("sql")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()

        sql_match = re.search(
            r"\b(?:SELECT|WITH)\b\s+.*?(?:;|$)",
            cleaned_text,
            re.IGNORECASE | re.DOTALL,
        )
        if sql_match:
            return sql_match.group(0).strip().removesuffix(";").strip()

        raise ValueError("LLM response did not contain a SQL statement.")


cloud_llm_client = CloudLLMClient()
