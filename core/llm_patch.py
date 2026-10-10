"""
LLM Token Tracking Patch.

Monkey-patches ChatOpenAI.invoke() to globally intercept ALL token usage
across every component in PLCHaT. Must be imported BEFORE any ChatOpenAI
instances are created.

Apply at the TOP of experiment scripts:

    import core.llm_patch  # noqa: F401 — side-effect import
"""

from langchain_openai import ChatOpenAI
from core.token_tracker import TokenTracker

_orig_invoke = ChatOpenAI.invoke


def _tracked_invoke(self, input, *args, **kwargs):
    response = _orig_invoke(self, input, *args, **kwargs)
    try:
        usage = response.response_metadata.get("token_usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if prompt_tokens or completion_tokens:
            TokenTracker.get().record(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
            )
    except Exception:
        pass  # silently ignore tracking failures
    return response


ChatOpenAI.invoke = _tracked_invoke

# Also patch ainvoke (async) for completeness  
if hasattr(ChatOpenAI, "ainvoke"):
    _orig_ainvoke = ChatOpenAI.ainvoke

    async def _tracked_ainvoke(self, input, *args, **kwargs):
        response = await _orig_ainvoke(self, input, *args, **kwargs)
        try:
            usage = response.response_metadata.get("token_usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            if prompt_tokens or completion_tokens:
                TokenTracker.get().record(
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                )
        except Exception:
            pass
        return response

    ChatOpenAI.ainvoke = _tracked_ainvoke
