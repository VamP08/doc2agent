"""One Groq call site, with failover across model candidates.

Free-tier model names get retired without notice — `llama-3.3-70b-versatile`
went 404 mid-project and took every chat down while the app still looked
healthy. Hardcoding one name means the next retirement is another outage, so
each role has a candidate list and the first model that answers wins.
"""

import os
import re
import time

from groq import Groq

# Strongest first. Override per role with GROQ_AGENT_MODEL / GROQ_EXTRACTION_MODEL
# / GROQ_ROUTER_MODEL to pin a single model.
AGENT_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
EXTRACTION_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
ROUTER_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

_GONE = ("model_not_found", "does not exist", "decommissioned", "has been deprecated")


# Groq's free tier budgets each model separately: requests and tokens per day,
# tokens per minute. A spent daily budget sits out until Groq says it frees up;
# a per-minute cap is waited out on the same model.
_RETRY_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s")
_cooldown: dict[str, float] = {}  # ponytail: per process; a second worker learns the hard way


def _retry_after(message: str) -> float | None:
    m = _RETRY_IN.search(message)
    return int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + float(m[3]) if m else None


def groq_client() -> Groq:
    """One retry for transient errors; rate limits are handled in complete()."""
    return Groq(max_retries=1)


class NoModelAvailable(RuntimeError):
    pass


def candidates(role: str, default: list[str]) -> list[str]:
    pinned = os.environ.get(f"GROQ_{role.upper()}_MODEL")
    return [pinned] if pinned else default


def complete(client: Groq, models: list[str], **kwargs):
    """Call chat.completions.create, moving to the next model when one is gone
    or has spent its budget. If every model is rate limited, the last limit is
    raised so the caller can tell the user which kind it was."""
    last: Exception | None = None
    for model in models:
        if _cooldown.get(model, 0) > time.monotonic():
            continue
        for attempt in range(3):
            try:
                return client.chat.completions.create(model=model, **kwargs)
            except Exception as exc:
                msg, last = str(exc), exc
                if any(marker in msg.lower() for marker in _GONE):
                    break
                if "rate_limit_exceeded" not in msg:
                    raise
                wait = _retry_after(msg)
                if "per minute" in msg and wait is not None and wait <= 60 and attempt < 2:
                    time.sleep(wait)
                    continue
                _cooldown[model] = time.monotonic() + (wait or 60)
                break
    if last is not None and "rate_limit_exceeded" in str(last):
        raise last
    raise NoModelAvailable(f"None of {models} are available on this Groq account: {last}")
