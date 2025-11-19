"""Dependency container for chat session components."""

from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from rich.console import Console

from uatu.chat_session.commands import SlashCommandHandler
from uatu.chat_session.handlers import MessageHandler
from uatu.config import Settings, get_settings
from uatu.permissions import PermissionHandler
from uatu.tools import create_system_tools_mcp_server
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
        console = Console()

        # UI components
        approval_prompt = ApprovalPrompt(console)
        renderer = ConsoleRenderer(console)

        # Permission handler with callbacks wired
        permission_handler = PermissionHandler()
        permission_handler.get_approval_callback = approval_prompt.get_bash_approval
        permission_handler.get_network_approval_callback = approval_prompt.get_network_approval

        # Command and message handlers
        command_handler = SlashCommandHandler(permission_handler, console)
        message_handler = MessageHandler(console)

        # Claude SDK options
        sdk_options = ClaudeAgentOptions(
            model=settings.uatu_model,
            system_prompt=system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
            max_turns=20,
            allowed_tools=Tools.ALL_ALLOWED_TOOLS,
            hooks={
                "PreToolUse": [HookMatcher(hooks=[permission_handler.pre_tool_use_hook])],
                # PostToolUse hook removed - we capture all tool results via
                # ToolResultBlock in the message stream instead (see handlers.py)
            },
            stderr=lambda msg: console.print(f"[dim red]SDK: {msg}[/dim red]"),
        )

        return cls(
            settings=settings,
            console=console,
            approval_prompt=approval_prompt,
            renderer=renderer,
            permission_handler=permission_handler,
            command_handler=command_handler,
            message_handler=message_handler,
            sdk_options=sdk_options,
        )
