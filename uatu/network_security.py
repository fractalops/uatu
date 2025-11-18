"""Network security utilities for URL validation and SSRF protection."""

import ipaddress
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Cloud metadata endpoints (AWS, GCP, Azure)
BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",  # AWS, Azure, DigitalOcean metadata
    "metadata.google.internal",  # GCP metadata
    "metadata",  # Generic cloud metadata
}

# Localhost variations
BLOCKED_LOCALHOST = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",  # IPv6 localhost
    "0000:0000:0000:0000:0000:0000:0000:0001",  # IPv6 localhost full
}


def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL for security concerns.

    Checks for:
        - Valid HTTP/HTTPS scheme
        - No localhost access (SSRF)
        - No private IP addresses (SSRF)
        - No cloud metadata endpoints
        - No suspicious URL patterns

        Args:
            url: The URL to validate

        Returns:
            Tuple of (is_valid, reason). If valid, reason is "OK".

        Examples:
            >>> validate_url("https://example.com")
            (True, 'OK')
            >>> validate_url("http://localhost")
            (False, 'Access to localhost blocked (SSRF protection)')
            >>> validate_url("http://192.168.1.1")
            (False, 'Access to private IP blocked (SSRF protection): 192.168.1.1')
    """
    if not url or not url.strip():
        return False, "URL cannot be empty"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {e}"

    # Check scheme
    if parsed.scheme not in ("http", "https"):
        return False, f"Only HTTP/HTTPS allowed, got: {parsed.scheme}"

    # Check hostname exists
    if not parsed.hostname:
        return False, "URL must have a hostname"

    hostname = parsed.hostname.lower()

    # Check for localhost
    if hostname in BLOCKED_LOCALHOST:
        return False, "Access to localhost blocked (SSRF protection)"

    # Check for cloud metadata endpoints
    if hostname in BLOCKED_METADATA_HOSTS:
        return False, f"Access to cloud metadata endpoint blocked: {hostname}"

    # Check for private IP addresses
    try:
        ip = ipaddress.ip_address(hostname)

        # Block loopback
        if ip.is_loopback:
            return False, f"Access to loopback address blocked: {hostname}"

        # Block private IPs
        if ip.is_private:
            return False, f"Access to private IP blocked (SSRF protection): {hostname}"

        # Block link-local (169.254.0.0/16)
        if ip.is_link_local:
            return False, f"Access to link-local address blocked: {hostname}"

        # Block reserved IPs
        if ip.is_reserved:
            return False, f"Access to reserved IP blocked: {hostname}"

    except ValueError:
        # Not an IP address, hostname is OK
        pass

    # Check for suspicious patterns in path/query
    suspicious_patterns = [
        (r"\.\./", "Path traversal detected"),
        (r"%2e%2e", "Encoded path traversal detected"),
        (r"file://", "File protocol detected in URL"),
    ]

    full_url = url.lower()
    for pattern, reason in suspicious_patterns:
        if re.search(pattern, full_url):
            return False, reason

    return True, "OK"


def sanitize_headers(headers: dict) -> dict:
    """Sanitize HTTP headers to prevent prompt injection.

    Only includes safe headers and truncates values.

        Args:
            headers: Raw headers from HTTP response

        Returns:
            Dictionary of sanitized headers

        Examples:
            >>> headers = {"content-type": "text/html", "x-custom": "value" * 100}
            >>> sanitized = sanitize_headers(headers)
            >>> "content-type" in sanitized
            True
            >>> "x-custom" in sanitized
            False
    """
    # Allowlist of safe headers to include
    safe_headers = {
        "content-type",
        "content-length",
        "content-encoding",
        "server",
        "cache-control",
        "date",
        "expires",
        "last-modified",
        "etag",
    }

    sanitized = {}
    for name, value in headers.items():
        name_lower = name.lower()

        # Only include safe headers
        if name_lower in safe_headers:
            # Truncate long values to prevent prompt injection
            if isinstance(value, str):
                sanitized[name_lower] = value[:200]
            else:
                sanitized[name_lower] = str(value)[:200]

    return sanitized


def is_valid_hostname(hostname: str) -> bool:
    """Validate hostname format (RFC 1123).

    Args:
            hostname: The hostname to validate

        Returns:
            True if valid hostname format

        Examples:
            >>> is_valid_hostname("example.com")
            True
            >>> is_valid_hostname("api.example.com")
            True
            >>> is_valid_hostname("not valid")
            False
    """
    if not hostname or len(hostname) > 253:
        return False

    # Check for command injection attempts
    dangerous_chars = [";", "&", "|", "$", "`", "(", ")", "<", ">", "\n", "\r"]
    if any(char in hostname for char in dangerous_chars):
        return False

    # RFC 1123 hostname pattern
    hostname_pattern = (
        r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
        r"[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
    )

    return bool(re.match(hostname_pattern, hostname))


def is_valid_ip(ip_str: str) -> bool:
    """Validate IP address format.

    Args:
            ip_str: The IP address string to validate

        Returns:
            True if valid IP address format

        Examples:
            >>> is_valid_ip("192.168.1.1")
            True
            >>> is_valid_ip("not an ip")
            False
    """
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False
