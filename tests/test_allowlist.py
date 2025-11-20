"""Tests for allowlist manager."""

import tempfile
from pathlib import Path

import pytest

from uatu.allowlist import AllowlistManager
from uatu.exceptions import InvalidCommandError


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def manager(temp_config_dir):
    """Create an AllowlistManager with temp directory."""
    return AllowlistManager(config_dir=temp_config_dir)


class TestGetBaseCommand:
    """Tests for get_base_command static method."""

    def test_normal_command(self):
        assert AllowlistManager.get_base_command("top -bn1") == "top"

    def test_single_word(self):
        assert AllowlistManager.get_base_command("top") == "top"

    def test_empty_string(self):
        assert AllowlistManager.get_base_command("") == ""

    def test_whitespace_only(self):
        assert AllowlistManager.get_base_command("   ") == ""

    def test_multiple_spaces(self):
        assert AllowlistManager.get_base_command("ps  aux") == "ps"

    def test_tabs(self):
        assert AllowlistManager.get_base_command("ps\taux") == "ps"


class TestIsAllowed:
    """Tests for is_allowed method."""

    def test_empty_command(self, manager):
        """Empty commands should not be allowed."""
        assert not manager.is_allowed("")

    def test_whitespace_command(self, manager):
        """Whitespace-only commands should not be allowed."""
        assert not manager.is_allowed("   ")

    def test_not_in_allowlist(self, manager):
        """Commands not in allowlist should not be allowed."""
        assert not manager.is_allowed("dh -h")

    def test_base_command_exact_match(self, manager):
        """Base command should allow exact match."""
        manager.add_command("top -bn1")
        assert manager.is_allowed("top")

    def test_base_command_with_different_args(self, manager):
        """Base command should allow different arguments."""
        manager.add_command("top -bn1")
        assert manager.is_allowed("top -bn2")
        assert manager.is_allowed("top -u root")

    def test_exact_command_match(self, manager):
        """Exact command should only allow exact match."""
        manager.add_command("rm -rf /tmp/test")
        assert manager.is_allowed("rm -rf /tmp/test")

    def test_exact_command_no_partial_match(self, manager):
        """Exact command should not allow partial matches."""
        manager.add_command("rm -rf /tmp/test")
        assert not manager.is_allowed("rm -rf /tmp/test2")
        assert not manager.is_allowed("rm -rf /")
        assert not manager.is_allowed("rm")

    def test_pattern_type_exact_match(self, manager):
        """Pattern type should allow exact match."""
        manager.add_command("docker", entry_type="pattern")
        assert manager.is_allowed("docker")

    def test_pattern_type_with_args(self, manager):
        """Pattern type should allow command with arguments."""
        manager.add_command("docker", entry_type="pattern")
        assert manager.is_allowed("docker ps")
        assert manager.is_allowed("docker run nginx")

    def test_pattern_type_no_prefix_confusion(self, manager):
        """Pattern type should not match commands with same prefix."""
        manager.add_command("rm", entry_type="pattern")
        assert manager.is_allowed("rm file.txt")
        # Should NOT match commands that just start with "rm"
        assert not manager.is_allowed("rmdir")
        assert not manager.is_allowed("rmdisk")


class TestAddCommand:
    """Tests for add_command method."""

    def test_add_safe_command_auto_detects_base(self, manager):
        """Safe commands should auto-detect as base type."""
        manager.add_command("top -bn1")
        entries = manager.get_entries()
        assert len(entries) == 1
        assert entries[0]["pattern"] == "top"
        assert entries[0]["type"] == "base"

    def test_empty_command_raises_error(self, manager):
        """Adding empty command should raise InvalidCommandError."""
        with pytest.raises(InvalidCommandError, match="Command cannot be empty"):
            manager.add_command("")

    def test_whitespace_command_raises_error(self, manager):
        """Adding whitespace-only command should raise InvalidCommandError."""
        with pytest.raises(InvalidCommandError, match="Command cannot be empty"):
            manager.add_command("   ")

    def test_add_dangerous_command_auto_detects_exact(self, manager):
        """Dangerous commands should auto-detect as exact type."""
        manager.add_command("rm -rf /tmp/test")
        entries = manager.get_entries()
        assert len(entries) == 1
        assert entries[0]["pattern"] == "rm -rf /tmp/test"
        assert entries[0]["type"] == "exact"

    def test_add_explicit_type(self, manager):
        """Explicit type should override auto-detection."""
        manager.add_command("top", entry_type="exact")
        entries = manager.get_entries()
        assert entries[0]["type"] == "exact"

    def test_duplicate_prevents_addition(self, manager):
        """Adding duplicate should not create second entry."""
        manager.add_command("top -bn1")
        manager.add_command("top -bn2")  # Same base command
        entries = manager.get_entries()
        assert len(entries) == 1

    def test_persistence(self, temp_config_dir):
        """Commands should persist across instances."""
        manager1 = AllowlistManager(config_dir=temp_config_dir)
        manager1.add_command("top -bn1")

        manager2 = AllowlistManager(config_dir=temp_config_dir)
        assert manager2.is_allowed("top")

    def test_adds_timestamp(self, manager):
        """Adding command should include timestamp."""
        manager.add_command("top")
        entries = manager.get_entries()
        assert "added" in entries[0]
        assert entries[0]["added"]  # Should not be empty


class TestRemoveCommand:
    """Tests for remove_command method."""

    def test_remove_existing_pattern(self, manager):
        """Removing existing pattern should return True."""
        manager.add_command("top")
        assert manager.remove_command("top")

    def test_remove_nonexistent_pattern(self, manager):
        """Removing nonexistent pattern should return False."""
        assert not manager.remove_command("top")

    def test_remove_actually_removes(self, manager):
        """Removed command should no longer be allowed."""
        manager.add_command("ls")
        manager.remove_command("ls")
        assert not manager.is_allowed("ls")

    def test_remove_persists(self, temp_config_dir):
        """Removal should persist across instances."""
        manager1 = AllowlistManager(config_dir=temp_config_dir)
        manager1.add_command("pwd")
        manager1.remove_command("pwd")

        manager2 = AllowlistManager(config_dir=temp_config_dir)
        assert not manager2.is_allowed("pwd")


class TestClear:
    """Tests for clear method."""

    def test_clear_removes_all(self, manager):
        """Clear should remove all entries."""
        manager.add_command("top")
        manager.add_command("ps")
        manager.clear()
        assert len(manager.get_entries()) == 0

    def test_clear_persists(self, temp_config_dir):
        """Clear should persist across instances."""
        manager1 = AllowlistManager(config_dir=temp_config_dir)
        manager1.add_command("top")
        manager1.clear()

        manager2 = AllowlistManager(config_dir=temp_config_dir)
        assert len(manager2.get_entries()) == 0


class TestFileCorruption:
    """Tests for handling corrupted files."""

    def test_corrupted_json_creates_fresh_allowlist(self, temp_config_dir):
        """Corrupted JSON should create fresh allowlist."""
        config_file = temp_config_dir / "allowlist.json"
        config_file.write_text("this is not valid json{{{")

        manager = AllowlistManager(config_dir=temp_config_dir)
        assert len(manager.get_entries()) == 0

    def test_missing_file_creates_fresh_allowlist(self, temp_config_dir):
        """Missing file should create fresh allowlist."""
        manager = AllowlistManager(config_dir=temp_config_dir)
        assert len(manager.get_entries()) == 0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_special_characters_in_command(self, manager):
        """Commands with special characters should work."""
        manager.add_command("grep 'pattern' file.txt")
        assert manager.is_allowed("grep 'pattern' file.txt")

    def test_pipes_and_redirects(self, manager):
        """Commands with pipes should work."""
        manager.add_command("ps aux | grep python")
        assert manager.is_allowed("ps aux | grep python")

    def test_very_long_command(self, manager):
        """Very long commands should work."""
        long_cmd = "echo " + "a" * 1000
        manager.add_command(long_cmd)
        assert manager.is_allowed(long_cmd)

    def test_unicode_command(self, manager):
        """Commands with unicode should work."""
        manager.add_command("echo 'Hello 世界'")
        assert manager.is_allowed("echo 'Hello 世界'")

    def test_newlines_in_command(self, manager):
        """Commands with newlines should work."""
        multiline = "echo 'line1\nline2'"
        manager.add_command(multiline)
        assert manager.is_allowed(multiline)
