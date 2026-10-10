# from setuptools import find_packages, setup

# setup(name="PLCHaT", version="1.0", packages=find_packages())

import os
from pathlib import Path
from langchain_openai import ChatOpenAI

# Reliable project root and execution directory
PROJECT_ROOT = Path(__file__).resolve().parent
EXECUTION_DIR = str(PROJECT_ROOT / "execution")

MATIEC_PATH = os.getenv("MATIEC_PATH", "/usr/local/lib/matiec")  # set matiec install path

# DeepSeek Configuration
# NOTE: "sk-xxx" is a placeholder. Set the DEEPSEEK_API_KEY environment variable.
deepseek_api_key_test = os.getenv("DEEPSEEK_API_KEY", "sk-xxx")
deepseek_base_url_test = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
deepseek_model = os.getenv("PLCHAT_DEEPSEEK_MODEL", "deepseek-chat")

# DashScope (Qwen) Configuration
dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "sk-xxx")
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY')

qwen_model = "qwen3-32b"  # ~32B dense, comparable to old Qwen2.5-32B-Instruct
qwen_api_key = dashscope_api_key
qwen_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Local Model Configuration
local_model = "qwen3-14B-local"
local_api_key = "qwen3-14B-local"  # Placeholder for local model API key
local_base_url = "http://localhost:8003/v1"

# Model Assignments - can be configured via environment
direct_llm_model = qwen_model
direct_llm_api_key = qwen_api_key
direct_llm_base_url = qwen_base_url

generator_model = os.getenv("PLCHAT_GEN_MODEL", qwen_model)
generator_api_key = os.getenv("PLCHAT_GEN_KEY", qwen_api_key)
generator_base_url = os.getenv("PLCHAT_GEN_BASE_URL", qwen_base_url)

evaluator_model = qwen_model
evaluator_api_key = qwen_api_key
evaluator_base_url = qwen_base_url

planner_model = qwen_model
planner_api_key = qwen_api_key
planner_base_url = qwen_base_url

# Monkey patch ChatOpenAI to handle thinking mode
_orig_init = ChatOpenAI.__init__
def _new_init(self, *args, **kwargs):
    model = kwargs.get('model', '')
    extra = {}
    if model.startswith('qwen3-') and not model.startswith('qwen3.'):
        extra = {"enable_thinking": False}
    if extra:
        kwargs.setdefault('extra_body', extra)
    _orig_init(self, *args, **kwargs)
ChatOpenAI.__init__ = _new_init
