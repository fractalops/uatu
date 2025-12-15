"""Dependency container for chat session components."""

import os
import secrets
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, PermissionResultAllow, PermissionResultDeny
from rich.console import Console

from uatu.agents import get_diagnostic_agents
from uatu.chat_session.commands import SlashCommandHandler
from uatu.chat_session.handlers import MessageHandler
from uatu.config import Settings, get_settings
from uatu.permissions import PermissionHandler
from uatu.telemetry import NoopTelemetry, TelemetryConfig, TelemetryEmitter
from uatu.tools import create_safe_mcp_server, create_system_tools_mcp_server
from uatu.tools.constants import Tools
from uatu.ui import ApprovalPrompt, ConsoleRenderer


@dataclass
class SessionComponents:
    """Container for chat session dependencies.

    This class groups all the dependencies needed by ChatSession,
    separating component construction from business logic.
    """

    settings: Settings
    console: Console
    approval_prompt: ApprovalPrompt
    renderer: ConsoleRenderer
    permission_handler: PermissionHandler
    command_handler: SlashCommandHandler
    message_handler: MessageHandler
    sdk_options: ClaudeAgentOptions
    telemetry: TelemetryEmitter | NoopTelemetry
    session_id: str
    session_salt: str

    @classmethod
    def create_default(cls, system_prompt: str) -> "SessionComponents":
        """Create default session components with proper wiring.

        Args:
            system_prompt: System prompt for the Claude SDK

        Returns:
            SessionComponents with all dependencies wired together
        """
        # Core dependencies
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to start a Uatu session.")

        # Configure console width based on settings
        console_width = settings.uatu_console_width
        if console_width is None:
            # Default: let Rich auto-detect and wrap intelligently
            console = Console()
        elif console_width == 0:
            # Use full terminal width
            terminal_size = shutil.get_terminal_size()
            console = Console(width=terminal_size.columns)
        else:
            # Use specific width
            console = Console(width=console_width)

        # UI components
        approval_prompt = ApprovalPrompt(console)
        renderer = ConsoleRenderer(console)

        # Telemetry
        session_id = str(uuid.uuid4())
        session_salt = secrets.token_hex(16)
        telemetry_config = TelemetryConfig(
            enabled=settings.uatu_enable_telemetry,
            path=Path(settings.uatu_telemetry_path),
            service_version=None,
        )
        telemetry = TelemetryEmitter(telemetry_config) if settings.uatu_enable_telemetry else NoopTelemetry()

        # Permission handler with callbacks wired
        permission_handler = PermissionHandler(console=console)
        permission_handler.get_approval_callback = approval_prompt.get_bash_approval
        permission_handler.get_network_approval_callback = approval_prompt.get_network_approval

        # Command and message handlers
        command_handler = SlashCommandHandler(permission_handler, console)
        message_handler = MessageHandler(
            console,
            telemetry=telemetry,
            session_id=session_id,
            session_salt=session_salt,
            settings=settings,
        )

        # Build allowed tools surface based on mode
        tools_mode = settings.uatu_tools_mode.lower()
        if tools_mode == "none":
            allowed_tools: list[str] = []
        elif tools_mode == "minimal":
            allowed_tools = [
                Tools.GET_SYSTEM_INFO,
                Tools.LIST_PROCESSES,
                Tools.GET_PROCESS_TREE,
                Tools.FIND_PROCESS_BY_NAME,
                Tools.CHECK_PORT_BINDING,
                Tools.READ_PROC_FILE,
                # Safe-hints are lightweight summaries and safe to include
                *Tools.SAFE_HINT_TOOLS,
            ]
        else:
            allowed_tools = Tools.ALL_ALLOWED_TOOLS

        # Enable Skills tool if configured
        if settings.uatu_enable_skills and "Skill" not in allowed_tools:
            allowed_tools = list(allowed_tools) + ["Skill"]

        async def sdk_can_use_tool(
            tool_name: str, input_data: dict, context
        ) -> PermissionResultAllow | PermissionResultDeny:
            """Leverage our permission handler as a can_use_tool callback."""
            # Block bash when read-only
            if Tools.is_bash_tool(tool_name) and settings.uatu_read_only:
                return PermissionResultDeny(message="Bash disabled by UATU_READ_ONLY")
            # Block known network commands if allow_network is false
            if tool_name == Tools.BASH:
                command = input_data.get("command", "")
                base_cmd = permission_handler.allowlist.get_base_command(command)
                if (
                    base_cmd in permission_handler.allowlist.BLOCKED_NETWORK_COMMANDS
                    and not settings.uatu_allow_network
                ):
                    return PermissionResultDeny(message=f"Network command '{base_cmd}' blocked by policy")
            # Allow otherwise (PreToolUse hook still runs)
            return PermissionResultAllow()

        async def post_tool_use_hook(input_data, tool_use_id, context):
            """Add lightweight context on errors from tools and guide safer scans."""
            tool_response = input_data.get("tool_response", "")
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {}) or {}

            # If list_processes returned nothing, guide the model to adjust filters or switch tools
            try:
                if tool_name == Tools.LIST_PROCESSES:
                    content = tool_response.get("content", []) if isinstance(tool_response, dict) else tool_response
                    if content in (None, [], ""):
                        return {
                            "systemMessage": (
                                "list_processes returned no results. Try lower filters "
                                "(min_cpu_percent=0.5, min_memory_mb=10) or use safe-hints top_processes."
                            ),
                            "reason": "No processes returned",
                            "hookSpecificOutput": {
                                "hookEventName": "PostToolUse",
                            },
                        }
            except Exception:
                pass

            # Disk scan guidance for Bash
            if tool_name == Tools.BASH:
                cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
                lower = cmd.lower()
                hints: list[str] = []
                if "du " in lower and "--max-depth" not in lower:
                    hints.append("Add --max-depth=1 and head -10; prefer MCP get_directory_sizes first.")
                if "find " in lower and "-size" in lower and ("/users" in lower or "~" in lower or "/home" in lower):
                    hints.append("Prefer MCP find_large_files or limit scope with head -10 and narrower paths.")
                if hints:
                    return {
                        "systemMessage": (
                            "Tighten disk scans: " + " ".join(hints) + " Avoid multiple concurrent du/find scans."
                        ),
                        "reason": "Disk scan too broad",
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                        },
                    }

            if tool_response and "error" in str(tool_response).lower():
                return {
                    "systemMessage": (
                        "Tool reported an error. Switch to MCP/safe-hints or apply tighter filters; "
                        "do not retry the same failing command."
                    ),
                    "reason": "Tool execution error - suggest safer fallback",
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": (
                            "Tool invocation failed; fall back to MCP or a safer, filtered command instead of retrying."
                        )
                    },
                }
            return {}

        async def pre_tool_use_shaping(input_data, tool_use_id, context):
            """Block redundant basics and unsafe disk scans before execution."""
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {}) or {}

            # Per-turn cache that works whether context is a dict or object
            def _get_ctx_cache(ctx) -> dict:
                if isinstance(ctx, dict):
                    cache = ctx.get("user_data")
                    if cache is None:
                        cache = {}
                        ctx["user_data"] = cache
                    return cache
                cache = getattr(ctx, "user_data", None)
                if cache is None:
                    cache = {}
                    try:
                        setattr(ctx, "user_data", cache)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                return cache

            ctx_cache = _get_ctx_cache(context)

            # Dedup basic disk tools per turn
            basic_tools = {
                Tools.DISK_SCAN_SUMMARY,
                Tools.GET_DIRECTORY_SIZES,
                Tools.FIND_LARGE_FILES,
                "mcp__safe-hints__disk_usage_summary",
            }
            if tool_name in basic_tools:
                seen = ctx_cache.get("seen_basics", set())
                if tool_name in seen:
                    return {
                        "systemMessage": "Skipping duplicate basic disk summary this turn.",
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Duplicate basic disk tool this turn",
                        },
                    }
                seen.add(tool_name)
                ctx_cache["seen_basics"] = seen

            # Shape heavy Bash disk scans and dedup df
            if tool_name == Tools.BASH:
                cmd = str(tool_input.get("command", "")).lower()
                if cmd.startswith("df ") or cmd.strip() == "df -h":
                    if ctx_cache.get("seen_df"):
                        return {
                            "systemMessage": "Skipping duplicate df this turn.",
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": "Duplicate df this turn",
                            },
                        }
                    ctx_cache["seen_df"] = True
                if "du " in cmd:
                    if "--max-depth" not in cmd and "-d " not in cmd:
                        return {
                            "systemMessage": "Use du with --max-depth=1 (or -d 1) and head -10 to bound output.",
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": "Unbounded du; add depth/head",
                            },
                        }
                    if "head" not in cmd:
                        return {
                            "systemMessage": "Add head -10 to du to bound output.",
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": "Unbounded du output; add head",
                            },
                        }
                if "find " in cmd and "-size" in cmd and "head" not in cmd:
                    return {
                        "systemMessage": "Prefer MCP find_large_files or add head -10 and narrow scope for find -size.",
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Broad find -size without head",
                        },
                    }

            return {}

        async def session_start_hook(input_data, tool_use_id, context):
            """Inject session metadata once per session."""
            import platform
            os_name = platform.system()
            return {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        f"Uatu session started | platform={os_name} | tools_mode={tools_mode} | "
                        f"read_only={settings.uatu_read_only} | prefer MCP and safe-hints over Bash; avoid sudo."
                    ),
                }
            }

        def _sdk_stderr(msg: str) -> None:
            lower = msg.lower()
            if "aborterror" in lower or "no assistant message found" in lower:
                return
            console.print(f"[dim red]SDK: {msg}[/dim red]")

        sdk_options_dict = {
            "model": settings.uatu_model,
            "system_prompt": system_prompt,
            "mcp_servers": {
                "system-tools": create_system_tools_mcp_server(),
                "safe-hints": create_safe_mcp_server(),
            },
            "max_turns": settings.uatu_max_turns,
            "max_budget_usd": settings.uatu_max_budget_usd,
            "allowed_tools": allowed_tools,
            "can_use_tool": sdk_can_use_tool,
            "hooks": {
                "PreToolUse": [HookMatcher(hooks=[permission_handler.pre_tool_use_hook, pre_tool_use_shaping])],
                "PostToolUse": [HookMatcher(hooks=[post_tool_use_hook])],
                "SessionStart": [HookMatcher(hooks=[session_start_hook])],
            },
            "stderr": _sdk_stderr,
        }

        # Skills settings: setting_sources + cwd
        if settings.uatu_enable_skills:
            sdk_options_dict["setting_sources"] = (
                settings.uatu_setting_sources if settings.uatu_setting_sources else ["user", "project"]
            )
            sdk_options_dict["cwd"] = os.getcwd()

        # Add specialized diagnostic subagents if enabled
        if settings.uatu_enable_subagents:
            sdk_options_dict["agents"] = get_diagnostic_agents()

        sdk_options = ClaudeAgentOptions(**sdk_options_dict)

        return cls(
            settings=settings,
            console=console,
            approval_prompt=approval_prompt,
            renderer=renderer,
            permission_handler=permission_handler,
            command_handler=command_handler,
            message_handler=message_handler,
            sdk_options=sdk_options,
            telemetry=telemetry,
            session_id=session_id,
            session_salt=session_salt,
        )
