"""
Ollama client with KV cache support for local model inference.
Handles shared schema context caching and prompt management.
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional
import ollama
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from backend.monitoring.logger import get_logger
from backend.core.schema.loader import schema_loader
from backend.core.rules.loader import rules_loader

logger = get_logger()
class OllamaConfig:
    """Configuration for Ollama client."""
    
    def __init__(self):
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
        self.keep_alive = int(os.getenv("OLLAMA_KEEP_ALIVE", "3600"))  # 1 hour default
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
        self.max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS", "512"))
        self.top_p = float(os.getenv("OLLAMA_TOP_P", "0.95"))
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))  # Context window size
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    @property
    def generate_options(self) -> Dict[str, Any]:
        """Get generation options for Ollama API calls."""
        return {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
            "top_p": self.top_p,
            "num_ctx": self.num_ctx,
        }


# Global config instance
ollama_config = OllamaConfig()

class StaticContextBuilder:
    """
    Builds one static context from all configured schemas.
    These contexts are cached by Ollama's KV cache.
    """
    
    _instance: Optional["StaticContextBuilder"] = None
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._context: Optional[str] = None
    
    def _load_system_prompt(self) -> str:
        """Load system prompt with base instructions."""
        return """You are an expert PostgreSQL SQL generator with deep knowledge of database schemas and business rules.

### CRITICAL INSTRUCTIONS:
- Generate ONLY SELECT statements - never DML/DDL
- Never use functions like NOW(), CURRENT_DATE, CURRENT_TIMESTAMP
- Always use literal date/time values based on the provided runtime context
- Always include LIMIT 1000 unless user specifies otherwise
- Return ONLY valid JSON with a 'sql' field
- No explanations, no markdown, just JSON

### OUTPUT FORMAT:
{"sql": "your SQL statement here"}
"""
    

    def _build_few_shot_examples(self) -> str:
        """Build few-shot examples for the company-specific e-commerce schema."""

        examples = (
            """
    ### FEW-SHOT EXAMPLES FOR CUSTOMERS AND GEOGRAPHY

    User: "Show customers located in Sao Paulo"
    Response: {"sql": "SELECT customer_id, customer_unique_id, customer_city, customer_state FROM public.customers WHERE LOWER(customer_city) = 'sao paulo' ORDER BY customer_unique_id LIMIT 1000"}

    User: "How many unique customers are represented in the customer records?"
    Response: {"sql": "SELECT COUNT(DISTINCT customer_unique_id) AS unique_customer_count FROM public.customers"}

    User: "List the states with the highest number of customers"
    Response: {"sql": "SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS unique_customer_count FROM public.customers GROUP BY customer_state ORDER BY unique_customer_count DESC LIMIT 1000"}

    User: "Show the geographic coordinates for a ZIP code prefix"
    Response: {"sql": "SELECT geolocation_zip_code_prefix, geolocation_lat, geolocation_lng, geolocation_city, geolocation_state FROM public.geolocation ORDER BY geolocation_zip_code_prefix LIMIT 1000"}
    """,

            """
    ### FEW-SHOT EXAMPLES FOR ORDERS AND DELIVERY

    User: "Show all delivered orders with their purchase dates"
    Response: {"sql": "SELECT order_id, customer_id, order_purchase_timestamp, order_delivered_customer_date, order_status FROM public.orders WHERE order_status = 'delivered' ORDER BY order_purchase_timestamp DESC LIMIT 1000"}

    User: "How many orders are there for each order status?"
    Response: {"sql": "SELECT order_status, COUNT(DISTINCT order_id) AS order_count FROM public.orders GROUP BY order_status ORDER BY order_count DESC"}

    User: "Find delivered orders that arrived later than their estimated delivery dates"
    Response: {"sql": "SELECT order_id, order_purchase_timestamp, order_delivered_customer_date, order_estimated_delivery_date FROM public.orders WHERE order_status = 'delivered' AND order_delivered_customer_date > order_estimated_delivery_date ORDER BY order_delivered_customer_date DESC LIMIT 1000"}

    User: "Calculate the average delivery time in days for delivered orders"
    Response: {"sql": "SELECT AVG(EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp)) / 86400.0) AS avg_delivery_days FROM public.orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL"}
    """,

            """
    ### FEW-SHOT EXAMPLES FOR PRODUCTS AND SELLERS

    User: "List products with their categories and weights"
    Response: {"sql": "SELECT product_id, product_category_name, product_weight_g, product_length_cm, product_height_cm, product_width_cm FROM public.products ORDER BY product_category_name, product_id LIMIT 1000"}

    User: "Which product categories contain the most products?"
    Response: {"sql": "SELECT product_category_name, COUNT(DISTINCT product_id) AS product_count FROM public.products GROUP BY product_category_name ORDER BY product_count DESC LIMIT 1000"}

    User: "Show sellers located in Rio de Janeiro"
    Response: {"sql": "SELECT seller_id, seller_city, seller_state FROM public.sellers WHERE LOWER(seller_city) = 'rio de janeiro' ORDER BY seller_id LIMIT 1000"}

    User: "Which sellers have the highest total item sales value?"
    Response: {"sql": "SELECT oi.seller_id, SUM(oi.price) AS item_sales_value FROM public.order_items oi JOIN public.orders o ON oi.order_id = o.order_id WHERE o.order_status = 'delivered' GROUP BY oi.seller_id ORDER BY item_sales_value DESC LIMIT 1000"}
    """,

            """
    ### FEW-SHOT EXAMPLES FOR ORDER ITEMS AND REVENUE

    User: "Show the items purchased in each order with their prices and freight charges"
    Response: {"sql": "SELECT order_id, order_item_id, product_id, seller_id, price, freight_value FROM public.order_items ORDER BY order_id, order_item_id LIMIT 1000"}

    User: "What is the total GMV from delivered orders?"
    Response: {"sql": "SELECT SUM(op.payment_value) AS gmv FROM public.orders o JOIN public.order_payments op ON o.order_id = op.order_id WHERE o.order_status = 'delivered'"}

    User: "Calculate the average order value for delivered orders"
    Response: {"sql": "SELECT SUM(op.payment_value) / NULLIF(COUNT(DISTINCT o.order_id), 0) AS average_order_value FROM public.orders o JOIN public.order_payments op ON o.order_id = op.order_id WHERE o.order_status = 'delivered'"}

    User: "How many units were sold in delivered orders?"
    Response: {"sql": "SELECT COUNT(*) AS units_sold FROM public.order_items oi JOIN public.orders o ON oi.order_id = o.order_id WHERE o.order_status = 'delivered'"}

    User: "Show the total freight value by seller"
    Response: {"sql": "SELECT seller_id, SUM(freight_value) AS total_freight_value FROM public.order_items GROUP BY seller_id ORDER BY total_freight_value DESC LIMIT 1000"}
    """,

            """
    ### FEW-SHOT EXAMPLES FOR PAYMENT ANALYTICS

    User: "Show the total value collected by each payment method"
    Response: {"sql": "SELECT payment_type, SUM(payment_value) AS total_payment_value FROM public.order_payments GROUP BY payment_type ORDER BY total_payment_value DESC"}

    User: "How many orders used each payment method?"
    Response: {"sql": "SELECT payment_type, COUNT(DISTINCT order_id) AS order_count FROM public.order_payments GROUP BY payment_type ORDER BY order_count DESC"}

    User: "List orders paid in installments, with the installment count and payment value"
    Response: {"sql": "SELECT order_id, payment_sequential, payment_type, payment_installments, payment_value FROM public.order_payments WHERE payment_installments > 1 ORDER BY payment_installments DESC, payment_value DESC LIMIT 1000"}
    """,

            """
    ### FEW-SHOT EXAMPLES FOR CUSTOMER REVIEWS

    User: "What is the average review score?"
    Response: {"sql": "SELECT AVG(review_score) AS average_review_score FROM public.order_reviews"}

    User: "How many positive reviews were recorded?"
    Response: {"sql": "SELECT COUNT(DISTINCT review_id) AS positive_review_count FROM public.order_reviews WHERE review_score >= 4"}

    User: "Show the number of reviews for each review score"
    Response: {"sql": "SELECT review_score, COUNT(DISTINCT review_id) AS review_count FROM public.order_reviews GROUP BY review_score ORDER BY review_score"}

    User: "Show review scores alongside order status"
    Response: {"sql": "SELECT o.order_id, o.order_status, r.review_score, r.review_creation_date FROM public.orders o JOIN public.order_reviews r ON o.order_id = r.order_id ORDER BY r.review_creation_date DESC LIMIT 1000"}
    """
        )

        return "\\n".join(examples)

    
    async def get_or_build_context(self) -> str:
        """
        Build or retrieve the shared static context.
        The context includes schema, business rules, and few-shot examples.
        """
        if self._context:
            logger.info("Using cached combined static context.")
            return self._context
        
        try:
            schema_text = await schema_loader.get_schema_text()
            rules_text = await rules_loader.get_rules_text()
            
            # Build context
            context_parts = [
                self._load_system_prompt(),
                "\n### DATABASE SCHEMA",
                schema_text,
                "\n### BUSINESS RULES",
                rules_text if rules_text else "No specific business rules configured.",
                self._build_few_shot_examples(),
                "\n### ADDITIONAL GUIDELINES",
                "- Always use the exact column names and table names from the schema",
                "- Always use schema-qualified table names",
                "- Use literal values for all comparisons (no dynamic functions)",
                "- Include LIMIT clause in every query",
                "- Use LEFT JOINs when you need to include null values",
                "- Apply business rules when interpreting user queries"
            ]
            
            context = "\n".join(context_parts)
            
            # Store in cache
            self._context = context
            logger.info("Built combined static context.")
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to build combined context: {e}", exc_info=True)
            raise
    
    def invalidate(self):
        """Invalidate cached contexts."""
        self._context = None
        logger.info("Invalidated combined context.")
    
# Global context builder instance
context_builder = StaticContextBuilder()


class OllamaClient:
    """
    Ollama client with KV cache support.
    """
    
    _instance: Optional["OllamaClient"] = None
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.config = ollama_config
        self._client = ollama.Client(host=self.config.host)
        
        logger.info(
            f"OllamaClient initialized",
            extra={
                "model": self.config.model,
                "host": self.config.host,
                "keep_alive": self.config.keep_alive
            }
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def generate(self, prompt: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate SQL using Ollama with KV cache.
        
        Args:
            prompt: The full prompt with static context + user query
            correlation_id: Request correlation identifier
        
        Returns:
            Generated text from Ollama.
        """
        try:
            # Execute generation
            response = self._client.generate(
                model=self.config.model,
                prompt=prompt,
                options=self.config.generate_options,
                keep_alive=self.config.keep_alive
            )
            
            return {
                "text": response.get('response', '').strip()
            }
            
        except Exception as e:
            logger.error(
                f"Ollama generation failed",
                extra={
                    "error": str(e),
                    "correlation_id": correlation_id
                },
                exc_info=True
            )
            raise
    
    async def generate_sql(
        self,
        user_query: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        
        context = await context_builder.get_or_build_context()
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        runtime_context = f"""
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
        
        full_prompt = context + runtime_context
        
        response = await self.generate(
            prompt=full_prompt,
            correlation_id=correlation_id
        )
        
        sql = self._parse_response(response["text"])
        
        return {"sql": sql}
    
    def _parse_response(self, text: str) -> str:
        """Parse the response to extract SQL."""
        # Remove markdown code blocks
        cleaned_text = re.sub(r'```(?:json)?\s*', '', text)
        cleaned_text = re.sub(r'```\s*$', '', cleaned_text)
        cleaned_text = cleaned_text.strip()

        try:
            result_json = json.loads(cleaned_text)
            return result_json.get("sql", "")
        except json.JSONDecodeError:
            pass

        sql_match = re.search(
            r'(SELECT|WITH)\s+.*?(?:;|$)',
            cleaned_text,
            re.IGNORECASE | re.DOTALL
        )
        
        if sql_match:
            sql = sql_match.group(0).strip()
            if sql.endswith(';'):
                sql = sql[:-1]
            return sql
        return cleaned_text
    
    async def warmup_cache(self) -> bool:
        """
        Warm up the KV cache with the shared schema context.
        This ensures the cache is built before production use.
        """
        try:
            logger.info("Warming up the combined schema context cache.")
            context = await context_builder.get_or_build_context()
            dummy_prompt = context + "\n\n### USER QUERY\nShow a sample query\n### RESPONSE (JSON)"
            
            self._client.generate(
                model=self.config.model,
                prompt=dummy_prompt,
                options={
                    "temperature": 0.1,
                    "num_predict": 50,
                    "top_p": 0.95
                },
                keep_alive=self.config.keep_alive
            )
            
            logger.info("Combined schema context cache warmed.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to warm combined schema context cache: {e}")
            return False


ollama_client = OllamaClient()

async def initialize_ollama() -> None:
    """
    Initialize the Ollama client and build the combined schema context.
    Optionally warm up caches.
    """
    logger.info("Initializing Ollama client...")

    try:
        await context_builder.get_or_build_context()
    except Exception as e:
        logger.error(f"Failed to build combined schema context: {e}")
    
    if os.getenv("OLLAMA_AUTO_WARMUP", "true").lower() == "true":
        logger.info("Auto-warming the combined schema context cache...")
        await ollama_client.warmup_cache()
    
    logger.info("Ollama client initialization complete")