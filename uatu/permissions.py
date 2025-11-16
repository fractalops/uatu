"""Permission handling for Uatu using SDK hooks."""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk import HookContext

from uatu.allowlist import AllowlistManager
from uatu.config import get_settings

logger = logging.getLogger(__name__)

# Type alias for approval callback
ApprovalCallback = Callable[[str, str], Awaitable[tuple[bool, bool]]]


class PermissionHandler:
    """Handles tool permissions with allowlist support.

    This class is designed to be testable and reusable, separating
    permission logic from UI concerns.
    """

    def __init__(self, allowlist: AllowlistManager | None = None):
        """Initialize permission handler.

        Args:
            allowlist: Optional allowlist manager. Creates new one if not provided.
        """
        self.allowlist = allowlist or AllowlistManager()
        # Callback for getting user approval - injected from UI layer
        self.get_approval_callback: ApprovalCallback | None = None

    async def pre_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        """Hook called before tool execution.

        Args:
            input_data: Tool input data containing tool_name and tool_input
            tool_use_id: Tool use identifier
            context: Hook context

        Returns:
            Hook response dict with permission decision

        Examples:
            >>> handler = PermissionHandler()
            >>> handler.get_approval_callback = lambda d, c: (True, False)
            >>> result = await handler.pre_tool_use_hook(
            ...     {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            ...     None,
            ...     HookContext()
            ... )
            >>> result["hookSpecificOutput"]["permissionDecision"]
            'allow'
        """
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Only handle Bash commands - everything else is read-only monitoring
        if tool_name != "Bash" and "bash" not in tool_name.lower():
            return {}  # Allow

        command = tool_input.get("command", "")
        description = tool_input.get("description", "")

        logger.debug(f"Permission check for command: {command!r}")

        # Get settings once for all checks
        settings = get_settings()

        # Check UATU_READ_ONLY setting - deny all bash commands if set
        if settings.uatu_read_only:
            logger.info(f"Command denied by UATU_READ_ONLY setting: {command!r}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Bash commands disabled by UATU_READ_ONLY setting",
                }
            }

        # Check for blocked network commands
        base_cmd = AllowlistManager.get_base_command(command)
        if base_cmd in AllowlistManager.BLOCKED_NETWORK_COMMANDS:
            if not settings.uatu_allow_network:
                logger.info(f"Network command blocked: {command!r}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Network command '{base_cmd}' blocked for security. Set UATU_ALLOW_NETWORK=true to override (not recommended).",
                    }
                }
            else:
                logger.warning(f"Network command allowed by UATU_ALLOW_NETWORK: {command!r}")

        # Check for suspicious patterns (even if base command is safe)
        for pattern in AllowlistManager.SUSPICIOUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                logger.warning(f"Suspicious pattern detected in command: {command!r}")
                # Force user approval - skip allowlist check
                break
        else:
            # No suspicious patterns found - check allowlist if UATU_REQUIRE_APPROVAL allows it
            if not settings.uatu_require_approval and self.allowlist.is_allowed(command):
                logger.info(f"Command auto-allowed (allowlisted): {command!r}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "message": "Command auto-allowed (allowlisted)",
                    }
                }

        # Need user approval - delegate to callback
        if not self.get_approval_callback:
            # No callback set - deny by default
            logger.warning(f"Command denied (no callback configured): {command!r}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "No approval callback configured",
                }
            }

        # Get approval from user (via UI layer)
        logger.debug(f"Requesting user approval for: {command!r}")
        approved, add_to_allowlist = await self.get_approval_callback(description, command)

        if not approved:
            logger.info(f"Command denied by user: {command!r}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "User declined to execute bash command",
                }
            }

        # Add to allowlist if requested
        if add_to_allowlist:
            self.allowlist.add_command(command)
            base_cmd = AllowlistManager.get_base_command(command)
            if base_cmd in AllowlistManager.SAFE_BASE_COMMANDS:
                logger.info(f"Command approved and '{base_cmd}' added to allowlist: {command!r}")
                message = f"Command allowed and '{base_cmd}' added to allowlist"
            else:
                logger.info(f"Command approved and added to allowlist (exact): {command!r}")
                message = "Command allowed and added to allowlist (exact match)"
        else:
            logger.info(f"Command approved (not added to allowlist): {command!r}")
            message = "Command allowed"

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "message": message,
            }
        }
