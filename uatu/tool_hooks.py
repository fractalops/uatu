"""Tool execution hooks for displaying results."""

import logging
from typing import Any

from claude_agent_sdk import HookContext

from uatu.config import get_settings
from uatu.ui.console import ConsoleRenderer

logger = logging.getLogger(__name__)


class ToolResultHook:
    """Hook to display tool result previews in the UI."""

    def __init__(self, renderer: ConsoleRenderer):
        """Initialize tool result hook.

        Args:
            renderer: Console renderer for displaying previews
        """
        self.renderer = renderer
        self.settings = get_settings()

    async def post_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        """Hook called after tool execution to show result preview.

        Args:
            input_data: Tool execution data containing tool_name, tool_input, and tool_response
            tool_use_id: Tool use identifier
            context: Hook context

        Returns:
            Empty dict (no modification to tool execution)
        """
        try:
            # Only show previews if enabled
            if not self.settings.uatu_show_tool_previews:
                return {}

            # The SDK might pass different structures - be defensive
            tool_name = input_data.get("tool_name", "")
            tool_response = input_data.get("tool_response")

            # Show preview if we have a response (even if empty string/dict)
            if tool_response is not None:
                self.renderer.show_tool_result(tool_name, tool_response)

        except Exception as e:
            # Silently log errors to avoid breaking tool execution
            logger.exception("Error in post_tool_use_hook: %s", e)

        return {}
