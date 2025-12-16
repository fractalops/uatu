"""Utility functions for Uatu.

This module provides common utility functions used throughout the codebase
to reduce boilerplate and improve code quality.
"""

from typing import Any


def safe_int(val: Any, default: int = 0) -> int:
    """Safely convert a value to int with a default fallback.

    Handles SDK quirks where parameters may be passed as empty dicts or None.

    Args:
        val: Value to convert (may be int, str, dict, None, etc.)
        default: Default value if conversion fails

    Returns:
        Integer value or default

    Examples:
        >>> safe_int(10)
        10
        >>> safe_int("5")
        5
        >>> safe_int({})  # SDK sometimes passes empty dict
        0
        >>> safe_int(None, default=10)
        10
    """
    if isinstance(val, dict) or val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert a value to float with a default fallback.

    Handles SDK quirks where parameters may be passed as empty dicts or None.

    Args:
        val: Value to convert (may be float, int, str, dict, None, etc.)
        default: Default value if conversion fails

    Returns:
        Float value or default

    Examples:
        >>> safe_float(3.14)
        3.14
        >>> safe_float("2.5")
        2.5
        >>> safe_float({})  # SDK sometimes passes empty dict
        0.0
        >>> safe_float(None, default=1.0)
        1.0
    """
    if isinstance(val, dict) or val is None:
        return default
    try:
        if isinstance(val, int | float):
            return float(val)
        return float(str(val))
    except (ValueError, TypeError):
        return default


def safe_str(val: Any, default: str = "") -> str:
    """Safely convert a value to string with a default fallback.

    Args:
        val: Value to convert
        default: Default value if conversion fails or val is None/dict

    Returns:
        String value or default

    Examples:
        >>> safe_str("hello")
        'hello'
        >>> safe_str(123)
        '123'
        >>> safe_str({})
        ''
        >>> safe_str(None, default="~")
        '~'
    """
    if isinstance(val, dict) or val is None:
        return default
    try:
        return str(val)
    except Exception:
        return default


def truncate_str(s: str, max_len: int = 60, suffix: str = "...") -> str:
    """Truncate a string to a maximum length with suffix.

    Args:
        s: String to truncate
        max_len: Maximum length including suffix
        suffix: Suffix to append when truncated

    Returns:
        Truncated string

    Examples:
        >>> truncate_str("hello world", 8)
        'hello...'
        >>> truncate_str("hi", 10)
        'hi'
    """
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix
