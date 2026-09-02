"""One Groq call site, with failover across model candidates.

Free-tier model names get retired without notice — `llama-3.3-70b-versatile`
went 404 mid-project and took every chat down while the app still looked
healthy. Hardcoding one name means the next retirement is another outage, so
each role has a candidate list and the first model that answers wins.
"""
import os

from groq import Groq

# Strongest first. Override per role with GROQ_AGENT_MODEL / GROQ_EXTRACTION_MODEL
# / GROQ_ROUTER_MODEL to pin a single model.
AGENT_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
EXTRACTION_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
ROUTER_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

_GONE = ("model_not_found", "does not exist", "decommissioned", "has been deprecated")


class NoModelAvailable(RuntimeError):
    pass


def candidates(role: str, default: list[str]) -> list[str]:
    pinned = os.environ.get(f"GROQ_{role.upper()}_MODEL")
    return [pinned] if pinned else default


def complete(client: Groq, models: list[str], **kwargs):
    """Call chat.completions.create, moving to the next model if one is gone.

    Only model-availability errors fall through. A rate limit is a real
    answer about the account, not about the model, so it propagates.
    """
    last: Exception | None = None
    for model in models:
        try:
            return client.chat.completions.create(model=model, **kwargs)
        except Exception as exc:
            if not any(marker in str(exc).lower() for marker in _GONE):
                raise
            last = exc
    raise NoModelAvailable(
        f"None of {models} are available on this Groq account: {last}"
    )
