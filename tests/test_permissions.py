"""Tests for permission handler."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from uatu.allowlist import AllowlistManager
from uatu.permissions import PermissionHandler


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def handler(temp_config_dir, monkeypatch):
    """Create a PermissionHandler with temp allowlist.

    Sets UATU_READ_ONLY=false to allow bash commands in tests.
    """
    # Disable read-only mode for tests that need to test bash permission logic
    monkeypatch.setenv("UATU_READ_ONLY", "false")

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
        assert "auto-allowed" in result["hookSpecificOutput"]["message"]

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
    async def test_add_to_allowlist_safe_command(self, handler):
        """Safe commands should be added as base pattern."""
        # Mock approval - user wants to add to allowlist
        handler.get_approval_callback = AsyncMock(return_value=(True, True))

        input_data = {
            "tool_name": "Bash",
            "tool_input": {"command": "top -bn1", "description": "Check CPU"},
        }

        result = await handler.pre_tool_use_hook(input_data, None, None)

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "'top'" in result["hookSpecificOutput"]["message"]

        # Verify it was added to allowlist
        entries = handler.allowlist.get_entries()
        assert len(entries) == 1
        assert entries[0]["pattern"] == "top"
        assert entries[0]["type"] == "base"

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
