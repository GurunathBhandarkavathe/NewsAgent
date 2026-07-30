from __future__ import annotations

import re
from typing import Any

from .config import Config


TOKEN_PATTERN = re.compile(r"\b(?:IG|EAA)[A-Za-z0-9_\-]{20,}\b")
ACCESS_TOKEN_QUERY_PATTERN = re.compile(r"(access_token=)[^&\s]+")


def redact_sensitive_meta_text(text: str, config: Config | None = None) -> str:
    redacted = text
    if config and config.meta_access_token:
        redacted = redacted.replace(config.meta_access_token, "[redacted]")
    redacted = ACCESS_TOKEN_QUERY_PATTERN.sub(r"\1[redacted]", redacted)
    return TOKEN_PATTERN.sub("[redacted]", redacted)


def meta_response_error_detail(response: Any, config: Config | None = None) -> str:
    payload = _safe_response_json(response)
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        parts = []
        if error.get("message"):
            parts.append(str(error["message"]))
        if error.get("type") or error.get("code"):
            meta_type = error.get("type") or "Meta error"
            code = error.get("code")
            parts.append(f"{meta_type} code {code}" if code else str(meta_type))
        if error.get("fbtrace_id"):
            parts.append(f"trace {error['fbtrace_id']}")
        if parts:
            return redact_sensitive_meta_text("; ".join(parts), config)

    text = getattr(response, "text", "").strip()
    if text:
        return redact_sensitive_meta_text(text, config)
    return "Meta returned an error."


def _safe_response_json(response: Any) -> dict:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
