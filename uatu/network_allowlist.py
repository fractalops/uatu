"""Network allowlist management for URL access control."""

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from uatu.exceptions import InvalidURLError

logger = logging.getLogger(__name__)


class NetworkAllowlistManager:
    """Manages allowed domains for network access (WebFetch, WebSearch, etc.)."""

    # Pre-approved domains for common diagnostic/documentation sites
    # These are safe, public resources commonly needed for troubleshooting
    DEFAULT_ALLOWED_DOMAINS = {
        # Documentation
        "docs.python.org",
        "docs.anthropic.com",
        "developer.mozilla.org",
        # Public diagnostic services
        "httpbin.org",
        "httpstat.us",
        "example.com",
        "example.org",
    }

    def __init__(self, config_dir: Path | None = None) -> None:
        """Initialize the network allowlist manager.

        Args:
            config_dir: Directory to store allowlist config. Defaults to ~/.config/uatu
        """
        if config_dir is None:
            config_dir = Path.home() / ".config" / "uatu"

        self.config_dir = config_dir
        self.config_file = config_dir / "network_allowlist.json"
        self._ensure_config_dir()
        self.allowlist = self._load_allowlist()

    def _ensure_config_dir(self) -> None:
        """Ensure config directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _load_allowlist(self) -> dict:
        """Load allowlist from config file."""
        if not self.config_file.exists():
            logger.debug(f"Network allowlist file not found, creating with defaults: {self.config_file}")
            return {"domains": list(self.DEFAULT_ALLOWED_DOMAINS)}

        try:
            with open(self.config_file) as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data.get('domains', []))} network allowlist entries from {self.config_file}")
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load network allowlist from {self.config_file}: {e}. Starting with defaults.")
            return {"domains": list(self.DEFAULT_ALLOWED_DOMAINS)}

    def _save_allowlist(self) -> None:
        """Save allowlist to config file."""
        with open(self.config_file, "w") as f:
            json.dump(self.allowlist, f, indent=2)

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from URL.

        Args:
            url: The URL to extract domain from

        Returns:
            The domain (netloc), or empty string if parsing fails

        Examples:
            >>> NetworkAllowlistManager.extract_domain("https://example.com/path")
            'example.com'
            >>> NetworkAllowlistManager.extract_domain("http://api.example.com:8080/endpoint")
            'api.example.com:8080'
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception as e:
            logger.warning(f"Failed to parse URL {url!r}: {e}")
            return ""

    def is_domain_allowed(self, url: str) -> bool:
        """Check if a URL's domain is allowed.

        Args:
            url: The URL to check

        Returns:
            True if the domain is allowed, False otherwise

        Examples:
            >>> manager = NetworkAllowlistManager()
            >>> manager.add_domain("example.com")
            >>> manager.is_domain_allowed("https://example.com/path")
            True
            >>> manager.is_domain_allowed("https://evil.com")
            False
        """
        domain = self.extract_domain(url)
        if not domain:
            logger.warning(f"Could not extract domain from URL: {url!r}")
            return False

        return domain in self.allowlist.get("domains", [])

    def add_domain(self, url_or_domain: str) -> None:
        """Add a domain to the allowlist.

        Args:
            url_or_domain: Either a full URL or just a domain

        Raises:
            ValueError: If domain is empty

        Examples:
            >>> manager = NetworkAllowlistManager()
            >>> manager.add_domain("https://example.com/path")
            >>> manager.is_domain_allowed("https://example.com/other")
            True
            >>> manager.add_domain("api.example.com")
            >>> manager.is_domain_allowed("https://api.example.com")
            True
        """
        # Try to extract domain (handles both URLs and bare domains)
        if url_or_domain.startswith(("http://", "https://")):
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        if not domain or not domain.strip():
            raise InvalidURLError("Domain cannot be empty")

        # Check if already exists
        if domain in self.allowlist.get("domains", []):
            logger.debug(f"Domain already in allowlist: {domain}")
            return

        # Add new entry
        logger.info(f"Adding domain to network allowlist: {domain}")
        self.allowlist.setdefault("domains", []).append(domain)

        # Add timestamp for audit trail
        self.allowlist.setdefault("history", []).append(
            {"domain": domain, "added": datetime.now().isoformat(), "action": "added"}
        )

        self._save_allowlist()

    def remove_domain(self, domain: str) -> bool:
        """Remove a domain from the allowlist.

        Args:
            domain: The domain to remove

        Returns:
            True if removed, False if not found

        Examples:
            >>> manager = NetworkAllowlistManager()
            >>> manager.add_domain("example.com")
            >>> manager.remove_domain("example.com")
            True
            >>> manager.remove_domain("example.com")
            False
        """
        domains = self.allowlist.get("domains", [])
        original_len = len(domains)

        # Filter out matching domain
        self.allowlist["domains"] = [d for d in domains if d != domain]

        if len(self.allowlist["domains"]) < original_len:
            logger.info(f"Removed domain from network allowlist: {domain}")

            # Add to history
            self.allowlist.setdefault("history", []).append(
                {"domain": domain, "removed": datetime.now().isoformat(), "action": "removed"}
            )

            self._save_allowlist()
            return True

        logger.debug(f"Domain not found in allowlist: {domain}")
        return False

    def clear(self) -> None:
        """Clear all allowlist entries (except defaults).

        Examples:
            >>> manager = NetworkAllowlistManager()
            >>> manager.add_domain("example.com")
            >>> manager.clear()
            >>> manager.is_domain_allowed("https://example.com")
            False
        """
        logger.info("Clearing all network allowlist entries (keeping defaults)")
        self.allowlist = {"domains": list(self.DEFAULT_ALLOWED_DOMAINS)}
        self._save_allowlist()

    def get_domains(self) -> list[str]:
        """Get all allowed domains.

        Returns:
            List of allowed domain strings
        """
        return self.allowlist.get("domains", [])

    def get_history(self) -> list[dict]:
        """Get history of domain additions/removals.

        Returns:
            List of history entries with timestamps
        """
        return self.allowlist.get("history", [])
