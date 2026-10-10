"""
Direct LLM Test Case Generator

Generates test cases using pure LLM prompting without iterative feedback.
This serves as the τ_llm baseline in RQ2 experiments.
"""

import json
import logging
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from core.data_types.exp_types import ExpUnifiedIR
from .prompts import BASELINE_SYSTEM_PROMPT, BASELINE_USER_TEMPLATE

logger = logging.getLogger(__name__)


class DirectLLMGenerator:
    """
    Direct LLM test case generator.

    Uses a single-shot LLM prompt to generate test cases targeting
    high coverage and edge case detection. No iterative feedback or
    coverage guidance.

    IMPORTANT: Mock mode is DISABLED. API key is required.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        max_cycles: int = 100,
        debug: bool = False,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize Direct LLM generator.

        Args:
            model_name: LLM model to use (from config if not provided)
            max_cycles: Maximum PLC cycles to generate
            debug: Enable debug logging
            api_key: API key (from config if not provided)
            base_url: API base URL (from config if not provided)

        Raises:
            RuntimeError: If API key is not available
        """
        # Load from config if not provided
        try:
            from config import get_direct_llm_config
            config = get_direct_llm_config()
        except ImportError:
            # Fallback to defaults if config module not available
            import os
            config = {
                "model": "deepseek-v3",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "base_url": "https://api.deepseek.com",
                "max_cycles": 30,
                "timeout_sec": 300,
            }

        self.model_name = model_name or config.get("model", "deepseek-v3")
        self.max_cycles = max_cycles
        self.debug = debug
        self.base_url = base_url or config.get("base_url", "https://api.deepseek.com")

        # Get API key from param, config, or env
        final_api_key = api_key or config.get("api_key", "")
        if not final_api_key:
            import os
            final_api_key = os.environ.get("OPENAI_API_KEY", "")

        # Import and validate API key
        try:
            from openai import OpenAI

            if not final_api_key:
                raise RuntimeError(
                    "Direct LLM API key not configured. Set one of:\n"
                    "  1. Environment variable: OPENAI_API_KEY\n"
                    "  2. In config/local.yaml: tools.direct_llm.api_key\n"
                    "  3. In config/local.yaml: llm.api_key"
                )

            self.client = OpenAI(
                api_key=final_api_key,
                base_url=self.base_url
            )
            self._use_openai = True

            # Initialize tiktoken for local token counting backup
            try:
                import tiktoken
                self.encoder = tiktoken.encoding_for_model("gpt-4o")
            except:
                import tiktoken
                self.encoder = tiktoken.get_encoding("cl100k_base")

        except ImportError as e:
            raise RuntimeError(f"OpenAI client not available: {e}. Install with: pip install openai")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to initialize DirectLLMGenerator: {e}")

    def _count_tokens(self, text: str) -> int:
        """Local token counting using tiktoken (fallback)."""
        if not text:
            return 0
        try:
            return len(self.encoder.encode(str(text)))
        except:
            return len(str(text)) // 4  # Rough fallback

    def _clean_json_output(self, text: str) -> dict:
        """Extract and parse JSON from LLM response."""
        text = str(text).strip()
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r"^```\s*|\s*```$", "", text, flags=re.MULTILINE)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                snippet = text[start : end + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    pass
        raise ValueError(f"DirectLLM: Failed to extract JSON. Raw: {text[:100]}...")

    def generate_case(
        self,
        st_code: str,
        schema_dict: Dict[str, Any],
        history: Optional[List[Dict[str, Any]]] = None,
        timeout_sec: int = 30
    ) -> Optional[ExpUnifiedIR]:
        """
        Generate a single test case using LLM.

        Args:
            st_code: ST source code
            schema_dict: Input schema dictionary
            history: Previous cycles for continuation
            timeout_sec: Generation timeout

        Returns:
            ExpUnifiedIR test case or None if generation failed

        Raises:
            RuntimeError: If API is not available
        """
        start_time = time.time()
        input_schema = self._format_schema(schema_dict)
        history_str = self._format_history(history)

        system_prompt = BASELINE_SYSTEM_PROMPT.format(
            max_cycles=self.max_cycles
        )

        user_prompt = BASELINE_USER_TEMPLATE.format(
            st_code=st_code,
            input_schema=input_schema,
            history=history_str or "None - starting fresh",
            max_cycles=self.max_cycles
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2000,
                timeout=timeout_sec
            )

            content = response.choices[0].message.content.strip()

            # Parse JSON from response
            sparse_timeline = self._clean_json_output(content)

            duration = time.time() - start_time

            # Extract token info (use API data, fallback to local counting)
            if response.usage:
                in_tokens = response.usage.prompt_tokens
                out_tokens = response.usage.completion_tokens
            else:
                # Fallback to local counting
                in_tokens = self._count_tokens(system_prompt + user_prompt)
                out_tokens = self._count_tokens(content)

            return ExpUnifiedIR(
                exp_id=f"llm_{int(time.time())}",
                target_st_path="",
                schema_path="",
                tester_type="direct_llm",
                total_cycles=len(sparse_timeline),
                sparse_timeline=sparse_timeline,
                metadata={
                    "generation_time_sec": duration,
                    "model": self.model_name,
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens
                }
            )

        except Exception as e:
            logger.error(f"Direct LLM generation failed: {e}")
            raise RuntimeError(f"DirectLLM generation failed: {e}")

    def generate_batch(
        self,
        st_code: str,
        schema_dict: Dict[str, Any],
        timeout_sec: int = 300,
        max_cases: int = 10
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        Generate multiple test cases within time budget.

        Args:
            st_code: ST source code
            schema_dict: Input schema dictionary
            timeout_sec: Total time budget for batch generation
            max_cases: Maximum number of cases to generate

        Returns:
            List of (sparse_timeline, stats) tuples
        """
        results = []
        start_time = time.time()

        while len(results) < max_cases and (time.time() - start_time) < timeout_sec:
            try:
                case = self.generate_case(st_code, schema_dict, timeout_sec=30)
                if case and case.sparse_timeline:
                    stats = {
                        "input_tokens": case.metadata.get("input_tokens", 0),
                        "output_tokens": case.metadata.get("output_tokens", 0),
                        "generation_time_sec": case.metadata.get("generation_time_sec", 0),
                        "total_tokens": case.metadata.get("input_tokens", 0) + case.metadata.get("output_tokens", 0)
                    }
                    results.append((case.sparse_timeline, stats))

                # Stop if not enough time for another generation
                if (timeout_sec - (time.time() - start_time)) < 20:
                    break

            except Exception as e:
                logger.warning(f"Batch generation item failed: {e}")
                break

        return results

    def _format_schema(self, schema_dict: Dict[str, Any]) -> str:
        """Format input schema for prompt."""
        inputs = schema_dict.get("input_vars", {})
        if not inputs:
            inputs = schema_dict.get("variables", {})

        lines = []
        for var_name, var_info in inputs.items():
            var_type = var_info.get("type", "UNKNOWN")
            desc = var_info.get("description", "")
            lines.append(f"  - {var_name} ({type}): {desc}")

        return "\n".join(lines) if lines else "  No variables defined"

    def _format_history(self, history: Optional[List[Dict[str, Any]]]) -> str:
        """Format history for prompt."""
        if not history:
            return ""

        lines = []
        for entry in history:
            cycle = entry.get("cycle", "?")
            inputs = entry.get("inputs", {})
            line = f"Cycle {cycle}: {inputs}"
            lines.append(line)

        return "\n".join(lines)
