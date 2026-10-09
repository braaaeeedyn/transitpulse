"""Optional Langfuse tracing (v4, OpenTelemetry-based). On only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are
set (LANGFUSE_HOST optional); otherwise it is a no-op and langfuse is never imported."""

import os
from typing import Any


def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def callbacks() -> list[Any]:
    """LangChain callback handlers to pass in the graph's config (an empty list without keys)."""
    if not enabled():
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]
