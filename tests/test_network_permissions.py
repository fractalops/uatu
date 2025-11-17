"""Tests for network permission handling."""

import pytest
from claude_agent_sdk import HookContext

from uatu.network_allowlist import NetworkAllowlistManager
from uatu.network_security import is_valid_hostname, is_valid_ip, sanitize_headers, validate_url
from uatu.permissions import PermissionHandler


class TestNetworkAllowlistManager:
    """Tests for NetworkAllowlistManager."""

    def test_extract_domain(self):
        """Test domain extraction from URLs."""
        assert NetworkAllowlistManager.extract_domain("https://example.com/path") == "example.com"
        assert NetworkAllowlistManager.extract_domain("http://api.example.com:8080/endpoint") == "api.example.com:8080"
        assert NetworkAllowlistManager.extract_domain("https://docs.anthropic.com/en/docs") == "docs.anthropic.com"
        assert NetworkAllowlistManager.extract_domain("invalid url") == ""

    def test_add_domain_from_url(self, tmp_path):
        """Test adding domain from full URL."""
        manager = NetworkAllowlistManager(config_dir=tmp_path)
        manager.add_domain("https://example.com/path")

        assert manager.is_domain_allowed("https://example.com/other")
        assert manager.is_domain_allowed("http://example.com")
        assert not manager.is_domain_allowed("https://evil.com")

    def test_add_domain_bare(self, tmp_path):
        """Test adding bare domain."""
        manager = NetworkAllowlistManager(config_dir=tmp_path)
        manager.add_domain("api.example.com")

        assert manager.is_domain_allowed("https://api.example.com")
        assert manager.is_domain_allowed("http://api.example.com/endpoint")

    def test_remove_domain(self, tmp_path):
        """Test removing a domain."""
        manager = NetworkAllowlistManager(config_dir=tmp_path)
        manager.add_domain("example.com")

        assert manager.is_domain_allowed("https://example.com")

        removed = manager.remove_domain("example.com")
        assert removed is True
        assert not manager.is_domain_allowed("https://example.com")

        # Removing again returns False
        removed = manager.remove_domain("example.com")
        assert removed is False

    def test_default_allowed_domains(self, tmp_path):
        """Test that default domains are pre-approved."""
        manager = NetworkAllowlistManager(config_dir=tmp_path)

        # Default domains should be allowed
        assert manager.is_domain_allowed("https://docs.python.org")
        assert manager.is_domain_allowed("https://docs.anthropic.com")
        assert manager.is_domain_allowed("https://httpbin.org/get")

    def test_persistence(self, tmp_path):
        """Test that allowlist persists across instances."""
        # Add domain with first instance
        manager1 = NetworkAllowlistManager(config_dir=tmp_path)
        manager1.add_domain("example.com")

        # Create new instance, should load persisted data
        manager2 = NetworkAllowlistManager(config_dir=tmp_path)
        assert manager2.is_domain_allowed("https://example.com")

    def test_clear_keeps_defaults(self, tmp_path):
        """Test that clear() keeps default domains."""
        manager = NetworkAllowlistManager(config_dir=tmp_path)
        manager.add_domain("custom.com")

        assert manager.is_domain_allowed("https://custom.com")
        assert manager.is_domain_allowed("https://docs.python.org")

        manager.clear()

        # Custom domain gone, defaults remain
        assert not manager.is_domain_allowed("https://custom.com")
        assert manager.is_domain_allowed("https://docs.python.org")


class TestNetworkSecurityFunctions:
    """Tests for network security functions."""

    def test_valid_https_url(self):
        """Test valid HTTPS URL."""
        valid, reason = validate_url("https://example.com")
        assert valid is True
        assert reason == "OK"

    def test_valid_http_url(self):
        """Test valid HTTP URL."""
        valid, reason = validate_url("http://example.com/path")
        assert valid is True
        assert reason == "OK"

    def test_blocks_localhost(self):
        """Test that localhost is blocked."""
        valid, reason = validate_url("http://localhost")
        assert valid is False
        assert "localhost" in reason.lower()

        valid, reason = validate_url("http://127.0.0.1")
        assert valid is False
        assert "SSRF" in reason

    def test_blocks_private_ips(self):
        """Test that private IPs are blocked."""
        valid, reason = validate_url("http://192.168.1.1")
        assert valid is False
        assert "private IP" in reason

        valid, reason = validate_url("http://10.0.0.1")
        assert valid is False
        assert "private IP" in reason

    def test_blocks_cloud_metadata(self):
        """Test that cloud metadata endpoints are blocked."""
        valid, reason = validate_url("http://169.254.169.254")
        assert valid is False
        assert "metadata" in reason.lower()

        valid, reason = validate_url("http://metadata.google.internal")
        assert valid is False
        assert "metadata" in reason.lower()

    def test_blocks_non_http_schemes(self):
        """Test that non-HTTP schemes are blocked."""
        valid, reason = validate_url("ftp://example.com")
        assert valid is False
        assert "HTTP/HTTPS" in reason

        valid, reason = validate_url("file:///etc/passwd")
        assert valid is False
        assert "HTTP/HTTPS" in reason

    def test_blocks_path_traversal(self):
        """Test that path traversal attempts are blocked."""
        valid, reason = validate_url("http://example.com/../../../etc/passwd")
        assert valid is False
        assert "traversal" in reason.lower()

    def test_sanitize_headers(self):
        """Test header sanitization."""
        headers = {
            "content-type": "text/html",
            "server": "nginx",
            "x-custom-header": "sensitive data",
            "set-cookie": "sessionid=abc123",
        }

        sanitized = sanitize_headers(headers)

        # Safe headers included
        assert "content-type" in sanitized
        assert "server" in sanitized

        # Unsafe headers excluded
        assert "x-custom-header" not in sanitized
        assert "set-cookie" not in sanitized

    def test_sanitize_headers_truncates(self):
        """Test that long header values are truncated."""
        headers = {
            "content-type": "x" * 300,  # Very long value
        }

        sanitized = sanitize_headers(headers)

        assert len(sanitized["content-type"]) == 200

    def test_is_valid_hostname(self):
        """Test hostname validation."""
        assert is_valid_hostname("example.com") is True
        assert is_valid_hostname("api.example.com") is True
        assert is_valid_hostname("sub.domain.example.com") is True

        # Invalid hostnames
        assert is_valid_hostname("not valid") is False
        assert is_valid_hostname("example.com; rm -rf /") is False
        assert is_valid_hostname("example.com$(evil)") is False

    def test_is_valid_ip(self):
        """Test IP validation."""
        assert is_valid_ip("192.168.1.1") is True
        assert is_valid_ip("8.8.8.8") is True
        assert is_valid_ip("::1") is True

        # Invalid IPs
        assert is_valid_ip("not an ip") is False
        assert is_valid_ip("999.999.999.999") is False


class TestWebFetchPermissions:
    """Tests for WebFetch permission handling."""

    @pytest.mark.asyncio
    async def test_webfetch_with_allowed_domain(self, tmp_path):
        """Test WebFetch with domain in allowlist."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        network_allowlist.add_domain("example.com")

        handler = PermissionHandler(network_allowlist=network_allowlist)

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://example.com/page"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "example.com" in result["hookSpecificOutput"]["message"]

    @pytest.mark.asyncio
    async def test_webfetch_invalid_url_blocked(self, tmp_path):
        """Test WebFetch with invalid URL is blocked."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "http://localhost/admin"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "validation failed" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_webfetch_requires_approval(self, tmp_path):
        """Test WebFetch requires user approval for new domain."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)

        # Mock approval callback
        async def mock_approval(tool_name: str, url: str) -> tuple[bool, bool]:
            assert tool_name == "WebFetch"
            assert "newsite.com" in url
            return (True, False)  # Approve but don't add to allowlist

        handler.get_network_approval_callback = mock_approval

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://newsite.com/page"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    @pytest.mark.asyncio
    async def test_webfetch_user_denial(self, tmp_path):
        """Test WebFetch denied by user."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)

        # Mock denial callback
        async def mock_approval(tool_name: str, url: str) -> tuple[bool, bool]:
            return (False, False)  # Deny

        handler.get_network_approval_callback = mock_approval

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://newsite.com/page"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "User declined" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_webfetch_add_to_allowlist(self, tmp_path):
        """Test WebFetch adds domain to allowlist when requested."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)

        # Mock approval with add to allowlist
        async def mock_approval(tool_name: str, url: str) -> tuple[bool, bool]:
            return (True, True)  # Approve and add to allowlist

        handler.get_network_approval_callback = mock_approval

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://newsite.com/page"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "added to allowlist" in result["hookSpecificOutput"]["message"]

        # Verify domain was added
        assert network_allowlist.is_domain_allowed("https://newsite.com/other")

    @pytest.mark.asyncio
    async def test_webfetch_no_callback_denies(self, tmp_path):
        """Test WebFetch denies if no approval callback is set."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)
        # No callback set

        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://newsite.com/page"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "No network approval callback" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_webfetch_ssrf_protection(self, tmp_path):
        """Test WebFetch blocks SSRF attempts."""
        network_allowlist = NetworkAllowlistManager(config_dir=tmp_path)
        handler = PermissionHandler(network_allowlist=network_allowlist)

        # Try to access AWS metadata
        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "http://169.254.169.254/latest/meta-data/"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "metadata" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()

        # Try to access private IP
        input_data = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "http://192.168.1.1/admin"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "private IP" in result["hookSpecificOutput"]["permissionDecisionReason"]


class TestWebSearchPermissions:
    """Tests for WebSearch permission handling."""

    @pytest.mark.asyncio
    async def test_websearch_allowed_by_default(self):
        """Test WebSearch is allowed (no URL validation needed)."""
        handler = PermissionHandler()

        input_data = {
            "tool_name": "WebSearch",
            "tool_input": {"query": "python documentation"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, HookContext())

        # WebSearch allowed without approval (for now)
        assert result == {}  # Allow
