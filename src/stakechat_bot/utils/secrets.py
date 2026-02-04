from __future__ import annotations
import os

def resolve_env(value: str) -> str:
    """Resolve values like 'env:VAR'."""
    if isinstance(value, str) and value.startswith("env:"):
        var = value.split(":", 1)[1].strip()
        return os.getenv(var, "")
    return value
