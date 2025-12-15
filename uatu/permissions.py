"""Permission handling for Uatu using SDK hooks."""

import asyncio
import logging
import platform
import re
import shutil
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from claude_agent_sdk import HookContext
from rich.console import Console

from uatu.allowlist import AllowlistManager
from uatu.audit import SecurityAuditor
from uatu.config import get_settings
from uatu.network_allowlist import NetworkAllowlistManager
from uatu.network_security import validate_url
from uatu.tools.constants import Tools

logger = logging.getLogger(__name__)


class PermissionDecision(Enum):
    """Permission decision outcomes."""

    ALLOW = "allow"
    DENY = "deny"


HOOK_EVENT_NAME = "PreToolUse"

# Type alias for approval callbacks
ApprovalCallback = Callable[[str, str], Awaitable[tuple[bool, bool]]]
NetworkApprovalCallback = Callable[[str, str], Awaitable[tuple[bool, bool]]]


def _build_hook_response(
    decision: PermissionDecision,
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Build standardized hook response.

    Args:
        decision: Permission decision (ALLOW or DENY)
        reason: Reason for denial (used when decision is DENY)
        message: Success message (used when decision is ALLOW)

    Returns:
        Hook response dictionary
    """
    response: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": HOOK_EVENT_NAME,
            "permissionDecision": decision.value,
        }
    }
    if reason:
        response["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if message:
        response["hookSpecificOutput"]["message"] = message
    return response


class PermissionHandler:
    """Handles tool permissions with allowlist support.

    This class is designed to be testable and reusable, separating
    permission logic from UI concerns.
    """

    def __init__(
        self,
        allowlist: AllowlistManager | None = None,
        network_allowlist: NetworkAllowlistManager | None = None,
        auditor: SecurityAuditor | None = None,
        console: Console | None = None,
    ):
        """Initialize permission handler.

        Args:
            allowlist: Optional allowlist manager. Creates new one if not provided.
            network_allowlist: Optional network allowlist manager. Creates new one if not provided.
            auditor: Optional security auditor. Creates new one if not provided.
            console: Optional rich console for user-friendly messages. Creates new one if not provided.
        """
        self.allowlist = allowlist or AllowlistManager()
        self.console = console or Console()
        self.network_allowlist = network_allowlist or NetworkAllowlistManager()
        self.auditor = auditor or SecurityAuditor()
        # Callbacks for getting user approval - injected from UI layer
        self.get_approval_callback: ApprovalCallback | None = None
        self.get_network_approval_callback: NetworkApprovalCallback | None = None
        # Lock to serialize approval prompts (only one at a time)
        self._approval_lock = asyncio.Lock()

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

        # Handle WebFetch and WebSearch
        if Tools.is_network_tool(tool_name):
            return await self._handle_network_tool(tool_name, tool_input)

        # Only handle Bash commands - everything else is read-only monitoring
        if not Tools.is_bash_tool(tool_name):
            return {}  # Allow

        command = tool_input.get("command", "")
        description = tool_input.get("description", "")

        logger.debug(f"Permission check for command: {command!r}")

        # Get settings once for all checks
        settings = get_settings()

        # Platform-specific guardrails (e.g., strace/ss on macOS)
        lower_cmd = command.lower()
        if "strace" in lower_cmd and platform.system() == "Darwin":
            return {
                "hookSpecificOutput": {
                    "hookEventName": HOOK_EVENT_NAME,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "strace is not available on macOS; use sample/lsof or dtruss (sudo) instead."
                    ),
                }
            }
        if "strace" in lower_cmd:
            if not shutil.which("strace"):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": HOOK_EVENT_NAME,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "strace is not installed; install it or use alternative tools (lsof/sample)."
                        ),
                    }
                }

        if platform.system() == "Darwin" and (" ss " in f" {lower_cmd} " or lower_cmd.strip().startswith("ss ")):
            return {
                "hookSpecificOutput": {
                    "hookEventName": HOOK_EVENT_NAME,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "ss is not available on macOS; use lsof -i -P -n or netstat instead.",
                }
            }

        # Check UATU_READ_ONLY setting - deny all bash commands if set
        if settings.uatu_read_only:
            logger.info(f"Command denied by UATU_READ_ONLY setting: {command!r}")
            self.auditor.log_bash_denial(
                command=command,
                reason="UATU_READ_ONLY setting enabled",
                description=description,
            )

            # Show user-friendly blocked message
            truncated_cmd = command[:60] + "..." if len(command) > 60 else command
            self.console.print(f"[yellow]  ⚠ Blocked: {truncated_cmd}[/yellow]")

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
                self.auditor.log_network_command_blocked(
                    command=command,
                    base_command=base_cmd,
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Network command '{base_cmd}' blocked for security."
                        f"Set UATU_ALLOW_NETWORK=true to override (not recommended).",
                    }
                }
            else:
                logger.warning(f"Network command allowed by UATU_ALLOW_NETWORK: {command!r}")

        # Check for suspicious patterns (even if base command is safe)
        for pattern in AllowlistManager.SUSPICIOUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                logger.warning(f"Suspicious pattern detected in command: {command!r}")
                self.auditor.log_suspicious_pattern(
                    command=command,
                    pattern=pattern,
                )
                # Force user approval - skip allowlist check
                break
        else:
            # No suspicious patterns found - check allowlist first
            if self.allowlist.is_allowed(command):
                logger.info(f"Command auto-allowed (allowlisted): {command!r}")
                self.auditor.log_bash_auto_approved(
                    command=command,
                    description=description,
                )
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
            self.auditor.log_bash_denial(
                command=command,
                reason="No approval callback configured",
                description=description,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "No approval callback configured",
                }
            }

        # Get approval from user (via UI layer)
        # Use lock to serialize approval prompts (only one at a time)
        logger.debug(f"Requesting user approval for: {command!r}")
        async with self._approval_lock:
            approved, add_to_allowlist = await self.get_approval_callback(description, command)

        # Log approval decision
        self.auditor.log_bash_approval(
            command=command,
            approved=approved,
            added_to_allowlist=add_to_allowlist,
            description=description,
        )

        if not approved:
            logger.info(f"Command denied by user: {command!r}")
            # Include risk category in denial reason to help agent understand context
            _, risk_text, _ = AllowlistManager.detect_risk_category(command)
            denial_reason = f"User declined to execute bash command (Risk: {risk_text})"
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": denial_reason,
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

    async def _handle_network_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle network tools (WebFetch, WebSearch) with URL approval.

        Args:
            tool_name: Name of the network tool
            tool_input: Tool input parameters

        Returns:
            Hook response dict with permission decision
        """
        # Extract URL from tool input
        url = tool_input.get("url", "")
        if not url:
            # WebSearch uses 'query' instead of 'url'
            query = tool_input.get("query", "")
            # For WebSearch, we approve based on the query itself
            # No URL validation needed
            if tool_name == "WebSearch":
                logger.debug(f"WebSearch requested with query: {query!r}")
                # For now, allow WebSearch without domain checking
                # Future: Could add search query allowlist
                return {}  # Allow

            logger.warning(f"{tool_name} called without URL")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"{tool_name} requires a URL",
                }
            }

        logger.debug(f"Network permission check for {tool_name}: {url!r}")
        # Validate URL for security (SSRF protection)
        is_valid, reason = validate_url(url)
        if not is_valid:
            logger.warning(f"URL validation failed for {url!r}: {reason}")
            self.auditor.log_ssrf_blocked(
                tool_name=tool_name,
                url=url,
                reason=reason,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"URL validation failed: {reason}",
                }
            }

        # Check if domain is in allowlist
        if self.network_allowlist.is_domain_allowed(url):
            domain = NetworkAllowlistManager.extract_domain(url)
            logger.info(f"Network access auto-allowed (domain allowlisted): {domain}")
            self.auditor.log_network_auto_approved(
                tool_name=tool_name,
                url=url,
                domain=domain,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "message": f"Domain '{domain}' is allowlisted",
                }
            }

        # Need user approval - delegate to callback
        if not self.get_network_approval_callback:
            # No callback set - deny by default
            logger.warning(f"Network access denied (no callback configured): {url!r}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "No network approval callback configured",
                }
            }

        # Get approval from user (via UI layer)
        # Use lock to serialize approval prompts (only one at a time)
        domain = NetworkAllowlistManager.extract_domain(url)
        logger.debug(f"Requesting user approval for network access: {url!r}")
        async with self._approval_lock:
            approved, add_to_allowlist = await self.get_network_approval_callback(tool_name, url)

        # Log approval decision
        self.auditor.log_network_approval(
            tool_name=tool_name,
            url=url,
            domain=domain,
            approved=approved,
            added_to_allowlist=add_to_allowlist,
        )

        if not approved:
            logger.info(f"Network access denied by user: {url!r}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "User declined network access",
                }
            }

        # Add domain to allowlist if requested
        if add_to_allowlist:
            self.network_allowlist.add_domain(url)
            logger.info(f"Network access approved and domain added to allowlist: {domain}")
            message = f"Network access allowed and '{domain}' added to allowlist"
        else:
            logger.info(f"Network access approved (not added to allowlist): {url!r}")
            message = "Network access allowed"

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "message": message,
            }
        }
