"""Tests for slash commands in interactive mode."""

from io import StringIO

import pytest
from rich.console import Console

from uatu.allowlist import AllowlistManager
from uatu.chat_session.commands import SlashCommandHandler
from uatu.permissions import PermissionHandler


@pytest.fixture
def temp_allowlist(tmp_path):
    """Create a temporary allowlist manager."""
    return AllowlistManager(config_dir=tmp_path)


@pytest.fixture
def console():
    """Create a console for testing."""
    return Console(file=StringIO(), force_terminal=True)


@pytest.fixture
def handler(temp_allowlist, console):
    """Create a slash command handler for testing."""
    permission_handler = PermissionHandler(allowlist=temp_allowlist)
    return SlashCommandHandler(permission_handler, console)


class TestAllowlistList:
    """Tests for /allowlist command (list)."""

    def test_list_empty_allowlist(self, handler, console):
        """Test listing empty allowlist."""
        handler.handle_command("/allowlist")
        output = console.file.getvalue()
        assert "No commands in allowlist" in output

    def test_list_with_entries(self, handler, console, temp_allowlist):
        """Test listing allowlist with entries."""
        temp_allowlist.add_command("ps aux")
        temp_allowlist.add_command("top -bn1")

        handler.handle_command("/allowlist")
        output = console.file.getvalue()
        assert "Allowlisted Commands" in output
        assert "ps" in output


class TestAllowlistAdd:
    """Tests for /allowlist add command."""

    def test_add_safe_command(self, handler, console, temp_allowlist):
        """Test adding a safe command."""
        handler.handle_command("/allowlist add ps aux")
        output = console.file.getvalue()

        assert "✓ Added to allowlist" in output
        assert "ps aux" in output
        assert temp_allowlist.is_allowed("ps")

    def test_add_credential_access_rejected(self, handler, console, temp_allowlist):
        """Test that credential access commands are rejected."""
        handler.handle_command("/allowlist add cat ~/.ssh/id_rsa")
        output = console.file.getvalue()

        assert "✗ Cannot add to allowlist: Credential Access" in output
        assert not temp_allowlist.is_allowed("cat ~/.ssh/id_rsa")

    def test_add_destructive_rejected(self, handler, console, temp_allowlist):
        """Test that destructive commands are rejected."""
        handler.handle_command("/allowlist add rm -rf /data")
        output = console.file.getvalue()

        assert "✗ Cannot add to allowlist: Destructive" in output
        assert not temp_allowlist.is_allowed("rm -rf /data")

    def test_add_network_command_rejected(self, handler, console, temp_allowlist):
        """Test that network commands are rejected."""
        handler.handle_command("/allowlist add curl http://example.com")
        output = console.file.getvalue()

        assert "✗ Cannot add network command to allowlist" in output
        assert not temp_allowlist.is_allowed("curl http://example.com")

    def test_add_suspicious_pattern_rejected(self, handler, console, temp_allowlist):
        """Test that suspicious patterns are rejected."""
        handler.handle_command("/allowlist add echo test | base64")
        output = console.file.getvalue()

        assert "✗ Cannot add to allowlist: Suspicious Pattern" in output

    def test_add_system_modification_warns(self, handler, console, temp_allowlist):
        """Test that system modification commands warn but allow."""
        handler.handle_command("/allowlist add chmod 755 /tmp/test")
        output = console.file.getvalue()

        assert "⚠ Warning: System Modification" in output
        assert "✓ Added to allowlist" in output
        assert temp_allowlist.is_allowed("chmod 755 /tmp/test")

    def test_add_duplicate_command(self, handler, console, temp_allowlist):
        """Test adding duplicate command."""
        handler.handle_command("/allowlist add ps aux")
        console.file.truncate(0)
        console.file.seek(0)

        # Add again
        handler.handle_command("/allowlist add ps aux")
        output = console.file.getvalue()

        # Should still succeed (duplicate check in AllowlistManager)
        assert "✓ Added to allowlist" in output

    def test_add_with_quotes_strips_them(self, handler, console, temp_allowlist):
        """Test that quotes are stripped from commands."""
        handler.handle_command('/allowlist add "ps aux"')
        output = console.file.getvalue()

        assert "✓ Added to allowlist" in output
        # Check that ps (without quotes) was added
        assert temp_allowlist.is_allowed("ps")

    def test_add_network_command_with_quotes_rejected(self, handler, console, temp_allowlist):
        """Test that network commands with quotes are still rejected."""
        handler.handle_command('/allowlist add "curl http://example.com"')
        output = console.file.getvalue()

        assert "✗ Cannot add network command to allowlist" in output
        assert "curl" in output
        assert not temp_allowlist.is_allowed("curl http://example.com")


class TestAllowlistRemove:
    """Tests for /allowlist remove command."""

    def test_remove_existing_pattern(self, handler, console, temp_allowlist):
        """Test removing existing pattern."""
        temp_allowlist.add_command("pwd")

        handler.handle_command("/allowlist remove pwd")
        output = console.file.getvalue()

        assert "Removed" in output and "'pwd'" in output and "allowlist" in output
        assert not temp_allowlist.is_allowed("pwd")

    def test_remove_nonexistent_pattern(self, handler, console):
        """Test removing nonexistent pattern."""
        handler.handle_command("/allowlist remove nonexistent")
        output = console.file.getvalue()

        assert "not found in allowlist" in output


class TestAllowlistClear:
    """Tests for /allowlist clear command."""

    def test_clear_allowlist(self, handler, console, temp_allowlist):
        """Test clearing allowlist."""
        temp_allowlist.add_command("ps aux")
        temp_allowlist.add_command("top -bn1")

        handler.handle_command("/allowlist clear")
        output = console.file.getvalue()

        assert "✓ Allowlist cleared" in output
        assert len(temp_allowlist.get_entries()) == 0


class TestInvalidCommands:
    """Tests for invalid slash commands."""

    def test_invalid_allowlist_subcommand(self, handler, console):
        """Test invalid /allowlist subcommand."""
        handler.handle_command("/allowlist invalid")
        output = console.file.getvalue()

        assert "Invalid" in output
        assert "allowlist" in output

    def test_allowlist_add_without_argument(self, handler, console):
        """Test /allowlist add without command argument."""
        handler.handle_command("/allowlist add")
        output = console.file.getvalue()

        assert "Invalid" in output
        assert "allowlist" in output

    def test_allowlist_remove_without_argument(self, handler, console):
        """Test /allowlist remove without pattern argument."""
        handler.handle_command("/allowlist remove")
        output = console.file.getvalue()

        assert "Invalid" in output
        assert "allowlist" in output


class TestOtherCommands:
    """Tests for other slash commands."""

    def test_help_command(self, handler):
        """Test /help command."""
        result = handler.handle_command("/help")
        assert result == "continue"

    def test_exit_command(self, handler):
        """Test /exit command."""
        result = handler.handle_command("/exit")
        assert result == "exit"

    def test_quit_command(self, handler):
        """Test /quit command."""
        result = handler.handle_command("/quit")
        assert result == "exit"

    def test_clear_command(self, handler, console):
        """Test /clear command."""
        result = handler.handle_command("/clear")
        assert result == "clear"
        output = console.file.getvalue()
        assert "Clearing conversation context" in output

    def test_unknown_command(self, handler, console):
        """Test unknown command."""
        handler.handle_command("/unknown")
        output = console.file.getvalue()
        assert "Unknown command" in output and "unknown" in output
