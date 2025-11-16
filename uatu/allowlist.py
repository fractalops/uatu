"""Command allowlist management for Uatu."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


class AllowlistManager:
    """Manages allowed commands for automatic approval."""

    # Common read-only monitoring commands that are safe to allowlist by base command
    SAFE_BASE_COMMANDS = {
        "top",
        "ps",
        "df",
        "free",
        "uptime",
        "vm_stat",
        "vmstat",
        "iostat",
        "netstat",
        "lsof",
        "who",
        "w",
        "last",
        "dmesg",
        "journalctl",
    }

    # Network commands that can exfiltrate data (blocked for security)
    BLOCKED_NETWORK_COMMANDS = {
        "curl",
        "wget",
        "nc",
        "ssh",
        "scp",
        "rsync",
        "ftp",
        "telnet",
    }

    # Suspicious patterns that indicate potential security issues
    # Even if base command is safe, these patterns force user approval
    SUSPICIOUS_PATTERNS = [
        r"\|.*curl",       # Piping to curl
        r"\|.*wget",       # Piping to wget
        r"\|.*nc\b",       # Piping to netcat
        r"\|.*ssh",        # Piping to ssh
        r"grep.*password", # Searching for passwords
        r"grep.*secret",   # Searching for secrets
        r"grep.*key",      # Searching for keys
        r"base64",         # Encoding (often used in exfiltration)
        r"xxd",            # Hex encoding
        r"\$\(",           # Command substitution in arguments
    ]

    def __init__(self, config_dir: Path | None = None) -> None:
        """Initialize the allowlist manager.

        Args:
            config_dir: Directory to store allowlist config. Defaults to ~/.config/uatu
        """
        if config_dir is None:
            config_dir = Path.home() / ".config" / "uatu"

        self.config_dir = config_dir
        self.config_file = config_dir / "allowlist.json"
        self._ensure_config_dir()
        self.allowlist = self._load_allowlist()

    def _ensure_config_dir(self) -> None:
        """Ensure config directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _load_allowlist(self) -> dict:
        """Load allowlist from config file."""
        if not self.config_file.exists():
            logger.debug(f"Allowlist file not found, creating new: {self.config_file}")
            return {"commands": []}

        try:
            with open(self.config_file) as f:
                data = json.load(f)
                logger.info(f"Loaded {len(data.get('commands', []))} allowlist entries from {self.config_file}")
                return data
        except (json.JSONDecodeError, OSError) as e:
            # If file is corrupted, start fresh
            logger.warning(f"Failed to load allowlist from {self.config_file}: {e}. Starting fresh.")
            return {"commands": []}

    def _save_allowlist(self) -> None:
        """Save allowlist to config file."""
        with open(self.config_file, "w") as f:
            json.dump(self.allowlist, f, indent=2)

    @staticmethod
    def get_base_command(command: str) -> str:
        """Extract base command (first word) from a command string.

        Args:
            command: The full command string

        Returns:
            The base command, or empty string if command is empty
        """
        return command.split()[0] if command and command.strip() else ""

    def is_allowed(self, command: str) -> bool:
        """Check if a command is allowed.

        Args:
            command: The command to check

        Returns:
            True if the command is allowed, False otherwise

        Examples:
            >>> manager = AllowlistManager()
            >>> manager.add_command("top -bn1")
            >>> manager.is_allowed("top")
            True
            >>> manager.is_allowed("top -bn2")
            True
            >>> manager.is_allowed("ps")
            False
        """
        # Safety check for empty commands
        if not command or not command.strip():
            return False

        # Check against stored allowlist
        for entry in self.allowlist.get("commands", []):
            pattern = entry.get("pattern", "")
            entry_type = entry.get("type", "exact")

            if entry_type == "base":
                # For base type, check if command starts with the pattern
                cmd_base = self.get_base_command(command)
                if cmd_base == pattern:
                    return True
            elif entry_type == "exact":
                # For exact type, command must match exactly
                if command == pattern:
                    return True
            elif entry_type == "pattern":
                # For pattern type, check if command starts with pattern followed by space or end
                if command == pattern or command.startswith(pattern + " "):
                    return True

        return False

    def add_command(
        self,
        command: str,
        entry_type: Literal["base", "exact", "pattern"] | None = None,
    ) -> None:
        """Add a command to the allowlist.

        Args:
            command: The command or pattern to add
            entry_type: Type of entry. If None, auto-detect based on command

        Raises:
            ValueError: If command is empty or contains invalid characters

        Examples:
            >>> manager = AllowlistManager()
            >>> manager.add_command("top -bn1")
            >>> manager.is_allowed("top")
            True
        """
        # Input validation
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")

        if "\n" in command or "\r" in command:
            logger.warning(f"Command contains newlines: {command!r}")

        # Auto-detect type if not specified
        if entry_type is None:
            base_cmd = self.get_base_command(command)
            if base_cmd in self.SAFE_BASE_COMMANDS:
                entry_type = "base"
                pattern = base_cmd
            else:
                # Default to exact for potentially dangerous commands
                entry_type = "exact"
                pattern = command
        else:
            pattern = command

        # Check if already exists
        for entry in self.allowlist.get("commands", []):
            if entry.get("pattern") == pattern and entry.get("type") == entry_type:
                logger.debug(f"Command already in allowlist: {pattern} ({entry_type})")
                return  # Already exists

        # Add new entry
        logger.info(f"Adding to allowlist: {pattern} ({entry_type})")
        self.allowlist.setdefault("commands", []).append(
            {
                "pattern": pattern,
                "type": entry_type,
                "added": datetime.now().isoformat(),
            }
        )
        self._save_allowlist()

    def remove_command(self, pattern: str) -> bool:
        """Remove a command from the allowlist.

        Args:
            pattern: The pattern to remove

        Returns:
            True if removed, False if not found

        Examples:
            >>> manager = AllowlistManager()
            >>> manager.add_command("top")
            >>> manager.remove_command("top")
            True
            >>> manager.remove_command("top")
            False
        """
        commands = self.allowlist.get("commands", [])
        original_len = len(commands)

        # Filter out matching entries
        self.allowlist["commands"] = [entry for entry in commands if entry.get("pattern") != pattern]

        if len(self.allowlist["commands"]) < original_len:
            logger.info(f"Removed from allowlist: {pattern}")
            self._save_allowlist()
            return True

        logger.debug(f"Pattern not found in allowlist: {pattern}")
        return False

    def clear(self) -> None:
        """Clear all allowlist entries.

        Examples:
            >>> manager = AllowlistManager()
            >>> manager.add_command("top")
            >>> manager.clear()
            >>> len(manager.get_entries())
            0
        """
        logger.info("Clearing all allowlist entries")
        self.allowlist = {"commands": []}
        self._save_allowlist()

    def get_entries(self) -> list[dict]:
        """Get all allowlist entries.

        Returns:
            List of allowlist entries
        """
        return self.allowlist.get("commands", [])
