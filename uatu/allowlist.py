"""Command allowlist management for Uatu."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from uatu.exceptions import InvalidCommandError

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
        r"\|.*curl",  # Piping to curl
        r"\|.*wget",  # Piping to wget
        r"\|.*nc\b",  # Piping to netcat
        r"\|.*ssh",  # Piping to ssh
        r"grep.*password",  # Searching for passwords
        r"grep.*secret",  # Searching for secrets
        r"grep.*key",  # Searching for keys
        r"base64",  # Encoding (often used in exfiltration)
        r"xxd",  # Hex encoding
        r"\$\(",  # Command substitution in arguments
    ]

    # Patterns that indicate credential/secret access attempts
    # These get special warning treatment in the UI
    CREDENTIAL_ACCESS_PATTERNS = [
        r"\.ssh",  # SSH directory access
        r"id_rsa",  # SSH private key
        r"id_ecdsa",  # SSH ECDSA key
        r"id_ed25519",  # SSH Ed25519 key
        r"\.pem\b",  # PEM certificates/keys
        r"\.key\b",  # Generic key files
        r"\.p12\b",  # PKCS12 certificates
        r"\.pfx\b",  # PFX certificates
        r"authorized_keys",  # SSH authorized keys
        r"known_hosts",  # SSH known hosts
        r"\.aws/credentials",  # AWS credentials
        r"\.kube/config",  # Kubernetes config
        r"\.docker/config\.json",  # Docker credentials
        r"\.npmrc",  # NPM credentials
        r"\.pypirc",  # PyPI credentials
        r"\.netrc",  # Generic credentials file
        r"\.git-credentials",  # Git credentials
        r"\.env",  # Environment files (often contain secrets)
        r"password",  # Password in command
        r"secret",  # Secret in command
        r"token",  # Token in command
        r"api[_-]?key",  # API key patterns
    ]

    # Patterns for destructive operations
    # These get high-risk warnings in the UI
    DESTRUCTIVE_PATTERNS = [
        r"rm\s+.*-r",  # Recursive delete
        r"dd\s+.*of=/dev/",  # Writing to block devices
        r"mkfs",  # Format filesystem
        r"fdisk",  # Partition manipulation
        r"shred",  # Secure file deletion
        r">/dev/sd[a-z]",  # Writing to disk devices
        r"truncate.*>",  # File truncation
        r":\(\)\{.*:\|:.*\};:",  # Fork bomb pattern
    ]

    # Patterns for privilege escalation or system modification
    SYSTEM_MODIFICATION_PATTERNS = [
        r"sudo\s+",  # Sudo usage
        r"chmod\s+[0-7]{3,4}",  # Permission changes
        r"chown\s+",  # Ownership changes
        r"chgrp\s+",  # Group changes
        r"usermod",  # User modification
        r"passwd",  # Password changes
        r"visudo",  # Sudoers editing
        r"/etc/shadow",  # Shadow file access
        r"/etc/passwd",  # Passwd file modification
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

    @classmethod
    def detect_risk_category(cls, command: str) -> tuple[str, str, str]:
        """Detect risk category and return risk level, text, and warning.

        Args:
            command: The command to analyze

        Returns:
            Tuple of (risk_style, risk_text, warning_message)
            - risk_style: Rich style string for coloring
            - risk_text: Short risk level text
            - warning_message: Detailed warning or empty string

        Examples:
            >>> AllowlistManager.detect_risk_category("ls -la ~/.ssh")
            ('red bold', 'Credential Access', 'This command may access SSH keys or certificates')
            >>> AllowlistManager.detect_risk_category("rm -rf /data")
            ('red bold', 'Destructive', 'This command can permanently delete files')
            >>> AllowlistManager.detect_risk_category("ps aux")
            ('green', 'Standard', '')
        """
        import re

        # Check for credential access patterns (highest priority warning)
        for pattern in cls.CREDENTIAL_ACCESS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return (
                    "red bold",
                    "Credential Access",
                    "This command may access SSH keys, certificates, or other credentials",
                )

        # Check for destructive patterns
        for pattern in cls.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return (
                    "red bold",
                    "Destructive",
                    "This command can permanently delete or modify data",
                )

        # Check for system modification patterns
        for pattern in cls.SYSTEM_MODIFICATION_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return (
                    "yellow bold",
                    "System Modification",
                    "This command will modify system configuration or permissions",
                )

        # Check base command for network commands
        base_cmd = cls.get_base_command(command)
        if base_cmd in cls.BLOCKED_NETWORK_COMMANDS:
            return (
                "yellow bold",
                "Network Command",
                "This command can transfer data over the network",
            )

        # Check for other suspicious patterns
        for pattern in cls.SUSPICIOUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return (
                    "yellow",
                    "Suspicious Pattern",
                    "This command contains patterns that may indicate security risks",
                )

        # No special patterns detected
        return ("green", "Standard", "")

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

        # Check if base command is in SAFE_BASE_COMMANDS
        base_cmd = self.get_base_command(command)
        if base_cmd in self.SAFE_BASE_COMMANDS:
            return True

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
            raise InvalidCommandError("Command cannot be empty")

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
