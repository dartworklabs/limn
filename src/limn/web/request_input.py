"""Recognize complete, unambiguous transport values before feature parsing."""

import json
import math
import re
from typing import Any
from urllib.parse import parse_qsl

from limn.web.errors import InputRejected


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, rejecting repeated decoded keys at any nesting depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    """Reject Python's nonstandard NaN and infinity JSON extensions."""
    raise ValueError("non-JSON numeric constant")


def _finite_float(value: str) -> float:
    """Reject exponent overflow instead of introducing infinity into valid JSON data."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def _unicode_scalars(value: object) -> None:
    """Require every decoded string, including keys, to encode as valid UTF-8."""
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            _unicode_scalars(key)
            _unicode_scalars(item)
    elif isinstance(value, list):
        for item in value:
            _unicode_scalars(item)


def json_object(raw: bytes) -> dict[str, Any] | InputRejected:
    """Decode an object without duplicate keys or non-JSON constants; empty input is {}."""
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant, parse_float=_finite_float)
        _unicode_scalars(value)
    except (ValueError, RecursionError):
        return InputRejected("본문이 올바른 JSON 이 아닙니다.", "bad_json")
    if not isinstance(value, dict):
        return InputRejected("본문은 JSON 객체여야 합니다.", "bad_json")
    return value


def query_values(raw: str) -> dict[str, list[str]] | InputRejected:
    """Decode a query once, rejecting repeated keys and malformed encodings.

    Raw URI text must be ASCII; Unicode values use UTF-8 percent encoding.
    Empty values participate in duplicate detection, then disappear to preserve
    existing default/document-selection behavior. Unknown unique keys remain data.
    """
    if not raw.isascii() or re.search(r"%(?![0-9a-fA-F]{2})", raw):
        return InputRejected("쿼리 문자열이 올바르지 않습니다.", "bad_query")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, errors="strict")
    except (ValueError, UnicodeError):
        return InputRejected("쿼리 문자열이 올바르지 않습니다.", "bad_query")
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for key, value in pairs:
        if key in seen:
            return InputRejected("쿼리 매개변수는 한 번만 보내세요.", "bad_query")
        seen.add(key)
        if value:
            result[key] = [value]
    return result
