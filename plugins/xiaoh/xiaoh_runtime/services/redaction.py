"""Small, shared redaction rules for durable evidence and user-visible output."""

from __future__ import annotations

import re
from typing import Any, Mapping


SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "cookie",
    "private_key",
    "private-key",
)


def redact_text(value: str, limit: int = 500) -> str:
    redacted = re.sub(
        r"(?i)\b(token|secret|password|cookie|private[_-]?key)\b\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        value,
    )
    redacted = re.sub(
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+",
        "Bearer [REDACTED]",
        redacted,
    )
    return redacted[:limit]


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if is_sensitive_key(key) else redact_value(item)
        for key, item in value.items()
    }


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace(" ", "_")
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)
