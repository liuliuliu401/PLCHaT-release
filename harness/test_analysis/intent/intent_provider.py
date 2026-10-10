"""
Test intent provider

# LLM analyzes ST code generation test intent.
"""

from pathlib import Path
import importlib.util
import json

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.generator.interface_extractor import InterfaceExtractor
from harness.compiler.generator import POUInfo
from core.data_types.test_analysis_types import TestIntent
import logging

# Load LLM config from config.py
spec = importlib.util.spec_from_file_location("config", PROJECT_ROOT / "config.py")
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class IntentProvider:
    """Get or generate test intent."""

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
        self.interface_extractor = InterfaceExtractor()

        # Directly use the LLM configuration from config.py
        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(
            temperature=0.3,
            model=config_module.generator_model,
            api_key=config_module.generator_api_key,
            base_url=config_module.generator_base_url,
        )

    def get_intent(
        self,
        st_path: Path,
        user_intent: str = None,
        pou_info: POUInfo = None
    ) -> TestIntent:
        """Get test intent."""
        if user_intent:
            return TestIntent(
                source="user",
                description=user_intent,
                safety_dimensions=[],
                functional_dimensions=[]
            )

        # LLM analyzes ST code generation intention
        return self._llm_generate_intent(st_path, pou_info)

    def _llm_generate_intent(
        self,
        st_path: Path,
        pou_info: POUInfo = None
    ) -> TestIntent:
        """LLM analyzes ST code generation test intent."""
        if pou_info is None:
            pou_info = self.interface_extractor.extract(st_path)

        st_code = st_path.read_text(encoding='utf-8')
        structure_info = self._extract_structure_info(pou_info)

        prompt = f"""
You are an industrial control testing and analysis expert. Please analyze the test intent of the following ST code.

【Code structure information】
{structure_info}

[ST code snippet]
{st_code[:2000]}

【Task】
Analyze this code and return JSON:
{{
Business Description
"safety_dimensions": ["boundary check", "error handling"]
"functional_dimensions": ["normal flow", "boundary conditions"]
}}
"""

        # Call LLM - directly invoke
        response = self.llm.invoke(prompt)
        result = self._parse_json_response(response.content)

        return TestIntent(
            source="llm_generated",
            description=result.get("description", ""),
            safety_dimensions=result.get("safety_dimensions", []),
            functional_dimensions=result.get("functional_dimensions", [])
        )

    def _extract_structure_info(self, pou_info: POUInfo) -> str:
        """Extract code structure information."""
        parts = [f"Program: {pou_info.name} ({pou_info.kind})"]
        if pou_info.outputs:
            parts.append("Output variables:")
            for var in pou_info.outputs[:10]:
                parts.append(f"  - {var.name} ({var.iec_type})")
        return "\n".join(parts)

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON response."""
        if "```json" in response:
            start = response.find("```json") + 8
            end = response.find("```", start)
            if end > start:
                response = response[start:end].strip()
        try:
            return json.loads(response)
        except:
            return {"description": response[:100]}


__all__ = ["IntentProvider"]
