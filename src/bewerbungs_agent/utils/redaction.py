"""Credential and PII redaction for outbound observability payloads.

Two passes:
- Structural pass (always on): replace literal values of environment variables
  whose names end in `_API_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD` with
  ``<REDACTED:NAME>``. Snapshot taken once at module import; refreshable via
  ``refresh_secret_snapshot()``.
- PII regex pass (full mode + mask_pii=True): replace email/phone/IBAN/postal
  patterns with ``<EMAIL>``/``<PHONE>``/``<IBAN>``/``<POSTAL>``.

Summary mode applies only the structural pass; PII can't appear in summaries
by construction.
"""

from __future__ import annotations

import os
import re
from typing import Any

_SECRET_SUFFIXES: tuple[str, ...] = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")

# (env_var_name, value) pairs captured at module load. Updated via
# refresh_secret_snapshot() for tests that set env vars after import.
_SECRET_SNAPSHOT: list[tuple[str, str]] = []


def refresh_secret_snapshot(env: dict[str, str] | None = None) -> None:
    """Re-read the environment and rebuild the snapshot of secret values."""
    global _SECRET_SNAPSHOT
    source = env if env is not None else os.environ
    snapshot: list[tuple[str, str]] = []
    for name, value in source.items():
        if not value:
            continue
        if any(name.endswith(suffix) for suffix in _SECRET_SUFFIXES):
            snapshot.append((name, value))
    # Order by value length DESC so longer values are matched before shorter
    # substrings (defence-in-depth against partial overlap).
    snapshot.sort(key=lambda pair: len(pair[1]), reverse=True)
    _SECRET_SNAPSHOT = snapshot


refresh_secret_snapshot()


# ---------------------------------------------------------------------------
# PII regex patterns
# ---------------------------------------------------------------------------

# Order matters: IBAN before phone (IBANs start with letters then digits;
# phone regex would otherwise capture the trailing digits).
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # IBAN: 2 letters + 2 digits + 10–30 alphanumerics
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "<IBAN>"),
    # Email
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    # Phone (E.164-ish: optional +, then digits/separators, total ≥ 8 digits)
    (re.compile(r"\+?\d[\d\s().\-]{7,}\d"), "<PHONE>"),
    # German-style postal block: 5-digit postcode + space + capitalised city.
    (re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]+\b"), "<POSTAL>"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _redact_env_vars(s: str) -> str:
    if not s:
        return s
    result = s
    for name, value in _SECRET_SNAPSHOT:
        if value in result:
            result = result.replace(value, f"<REDACTED:{name}>")
    return result


def _redact_pii(s: str) -> str:
    if not s:
        return s
    result = s
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redact_string(s: str, *, mode: str, mask_pii: bool) -> str:
    cleaned = _redact_env_vars(s)
    if mode == "full" and mask_pii:
        cleaned = _redact_pii(cleaned)
    return cleaned


def redact(value: Any, *, mode: str = "summary", mask_pii: bool = True) -> Any:
    """Walk *value* recursively, redacting strings.

    Args:
        value:     dict / list / str / scalar.
        mode:      "summary" (env-var values only) or "full" (env-var + PII regex).
        mask_pii:  Only meaningful in full mode. Defaults True. False disables
                   the PII regex pass but never the env-var pass.

    Returns a new structure; the input is not mutated.
    """
    if isinstance(value, str):
        return _redact_string(value, mode=mode, mask_pii=mask_pii)
    if isinstance(value, dict):
        return {k: redact(v, mode=mode, mask_pii=mask_pii) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, mode=mode, mask_pii=mask_pii) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v, mode=mode, mask_pii=mask_pii) for v in value)
    # Scalars (int, float, bool, None) and other types pass through unchanged.
    return value


# Re-export for tests
__all__ = (
    "redact",
    "refresh_secret_snapshot",
)
