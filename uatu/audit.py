"""Security audit logging for Uatu."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SecurityAuditor:
    """Logs security events to structured JSONL file for audit and compliance."""

    def __init__(self, log_dir: Path | None = None) -> None:
        """Initialize security auditor.

        Args:
            log_dir: Directory for audit logs. Defaults to ~/.uatu
        """
        if log_dir is None:
            log_dir = Path.home() / ".uatu"

        self.log_dir = log_dir
        self.audit_file = log_dir / "security.jsonl"
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure log directory exists with secure permissions."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Set restrictive permissions (owner read/write only)
        try:
            self.log_dir.chmod(0o700)
        except Exception as e:
            logger.warning(f"Could not set secure permissions on {self.log_dir}: {e}")

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write event to JSONL audit log.

        Args:
            event: Event dictionary to log
        """
        try:
            # Ensure file has restrictive permissions
            if not self.audit_file.exists():
                self.audit_file.touch(mode=0o600)

            # Append event as JSON line
            with open(self.audit_file, "a") as f:
                f.write(json.dumps(event) + "\n")

        except Exception as e:
            logger.error(f"Failed to write audit event: {e}")

    def log_bash_approval(
        self,
        command: str,
        approved: bool,
        added_to_allowlist: bool,
        description: str = "",
    ) -> None:
        """Log bash command approval decision.

        Args:
            command: The bash command
            approved: Whether user approved execution
            added_to_allowlist: Whether command was added to allowlist
            description: Command description from agent
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "bash_command_approval",
            "command": command,
            "description": description,
            "approved": approved,
            "added_to_allowlist": added_to_allowlist,
        }
        self._write_event(event)
        logger.debug(f"Audit: Bash command {'approved' if approved else 'denied'}: {command!r}")

    def log_bash_denial(
        self,
        command: str,
        reason: str,
        description: str = "",
    ) -> None:
        """Log bash command automatic denial.

        Args:
            command: The bash command
            reason: Reason for denial
            description: Command description from agent
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "bash_command_denied",
            "command": command,
            "description": description,
            "reason": reason,
        }
        self._write_event(event)
        logger.debug(f"Audit: Bash command denied: {command!r} - {reason}")

    def log_bash_auto_approved(
        self,
        command: str,
        description: str = "",
    ) -> None:
        """Log bash command auto-approved via allowlist.

        Args:
            command: The bash command
            description: Command description from agent
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "bash_command_auto_approved",
            "command": command,
            "description": description,
        }
        self._write_event(event)
        logger.debug(f"Audit: Bash command auto-approved: {command!r}")

    def log_network_approval(
        self,
        tool_name: str,
        url: str,
        domain: str,
        approved: bool,
        added_to_allowlist: bool,
    ) -> None:
        """Log network access approval decision.

        Args:
            tool_name: WebFetch or WebSearch
            url: The URL being accessed
            domain: Extracted domain
            approved: Whether user approved access
            added_to_allowlist: Whether domain was added to allowlist
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "network_access_approval",
            "tool": tool_name,
            "url": url,
            "domain": domain,
            "approved": approved,
            "added_to_allowlist": added_to_allowlist,
        }
        self._write_event(event)
        logger.debug(f"Audit: Network access {'approved' if approved else 'denied'}: {domain}")

    def log_network_auto_approved(
        self,
        tool_name: str,
        url: str,
        domain: str,
    ) -> None:
        """Log network access auto-approved via domain allowlist.

        Args:
            tool_name: WebFetch or WebSearch
            url: The URL being accessed
            domain: Extracted domain
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "network_access_auto_approved",
            "tool": tool_name,
            "url": url,
            "domain": domain,
        }
        self._write_event(event)
        logger.debug(f"Audit: Network access auto-approved: {domain}")

    def log_ssrf_blocked(
        self,
        tool_name: str,
        url: str,
        reason: str,
    ) -> None:
        """Log SSRF attack blocked.

        Args:
            tool_name: WebFetch or WebSearch
            url: The blocked URL
            reason: Reason for blocking (e.g., "private IP")
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "ssrf_blocked",
            "tool": tool_name,
            "url": url,
            "reason": reason,
            "severity": "high",
        }
        self._write_event(event)
        logger.warning(f"Audit: SSRF blocked - {url} - {reason}")

    def log_network_command_blocked(
        self,
        command: str,
        base_command: str,
    ) -> None:
        """Log network command blocked (curl, wget, etc).

        Args:
            command: Full command string
            base_command: Base command that was blocked (curl, wget, etc)
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "network_command_blocked",
            "command": command,
            "base_command": base_command,
            "severity": "medium",
        }
        self._write_event(event)
        logger.info(f"Audit: Network command blocked: {base_command}")

    def log_suspicious_pattern(
        self,
        command: str,
        pattern: str,
    ) -> None:
        """Log suspicious pattern detected in command.

        Args:
            command: Full command string
            pattern: The suspicious pattern matched
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "suspicious_pattern_detected",
            "command": command,
            "pattern": pattern,
            "severity": "medium",
        }
        self._write_event(event)
        logger.warning(f"Audit: Suspicious pattern detected: {pattern}")

    def log_allowlist_modification(
        self,
        action: str,
        entry_type: str,
        pattern: str,
    ) -> None:
        """Log modification to command allowlist.

        Args:
            action: "added" or "removed"
            entry_type: "base", "exact", or "pattern"
            pattern: The allowlist pattern
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "allowlist_modified",
            "action": action,
            "entry_type": entry_type,
            "pattern": pattern,
        }
        self._write_event(event)
        logger.info(f"Audit: Allowlist {action}: {pattern} ({entry_type})")

    def log_network_allowlist_modification(
        self,
        action: str,
        domain: str,
    ) -> None:
        """Log modification to network allowlist.

        Args:
            action: "added" or "removed"
            domain: The domain
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "network_allowlist_modified",
            "action": action,
            "domain": domain,
        }
        self._write_event(event)
        logger.info(f"Audit: Network allowlist {action}: {domain}")

    def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent audit events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries, most recent first
        """
        if not self.audit_file.exists():
            return []

        events = []
        try:
            with open(self.audit_file) as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))

            # Return most recent events first
            return events[-limit:][::-1]

        except Exception as e:
            logger.error(f"Failed to read audit events: {e}")
            return []

    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get events of a specific type.

        Args:
            event_type: Event type to filter by
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries, most recent first
        """
        all_events = self.get_recent_events(limit * 2)  # Get extra to filter
        filtered = [e for e in all_events if e.get("event_type") == event_type]
        return filtered[:limit]

    def get_security_summary(self) -> dict[str, Any]:
        """Get security summary statistics.

        Returns:
            Dictionary with security metrics
        """
        events = self.get_recent_events(limit=1000)

        summary = {
            "total_events": len(events),
            "bash_approvals": 0,
            "bash_denials": 0,
            "network_approvals": 0,
            "network_denials": 0,
            "ssrf_blocks": 0,
            "network_command_blocks": 0,
            "suspicious_patterns": 0,
        }

        for event in events:
            event_type = event.get("event_type")

            if event_type == "bash_command_approval":
                if event.get("approved"):
                    summary["bash_approvals"] += 1
                else:
                    summary["bash_denials"] += 1

            elif event_type == "bash_command_denied":
                summary["bash_denials"] += 1

            elif event_type == "network_access_approval":
                if event.get("approved"):
                    summary["network_approvals"] += 1
                else:
                    summary["network_denials"] += 1

            elif event_type == "ssrf_blocked":
                summary["ssrf_blocks"] += 1

            elif event_type == "network_command_blocked":
                summary["network_command_blocks"] += 1

            elif event_type == "suspicious_pattern_detected":
                summary["suspicious_patterns"] += 1

        return summary
