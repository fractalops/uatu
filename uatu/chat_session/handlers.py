"""Message and streaming response handlers."""

import sys

from claude_agent_sdk import ClaudeSDKClient, ResultMessage
from rich.console import Console

from uatu.chat_session.stats import SessionStats
from uatu.config import get_settings
from uatu.ui.console import ConsoleRenderer
from uatu.ui.markdown import LeftAlignedMarkdown


class MessageHandler:
    """Handles message streaming and display."""

    def __init__(self, console: Console):
        """Initialize message handler.

        Args:
            console: Rich console for output
        """
        self.console = console
        self.renderer = ConsoleRenderer(console)
        self.settings = get_settings()
        # Map tool_use_id to tool_name for matching results to tools
        self.tool_use_map: dict[str, str] = {}
        # Track session statistics
        self.stats = SessionStats()

    def reset_stats(self) -> None:
        """Reset session statistics (called when context is cleared)."""
        self.stats.reset()

    async def handle_message(self, client: ClaudeSDKClient, user_message: str) -> None:
        """Handle a user message and stream response.

        Uses receive_messages() instead of receive_response() to capture ALL
        tool results (including Bash) via ToolResultBlock in the message stream.
        PostToolUse hooks only fire for MCP tools, so we capture results here.

        Args:
            client: Claude SDK client
            user_message: User's message
        """
        response_text = ""
        spinner = None
        has_tty_output = sys.stdout.isatty()

        try:
            # Show progress indicator - spinner for TTY output, simple message otherwise
            if has_tty_output:
                spinner = self.renderer.create_spinner("Pondering...")
                spinner.start()
            else:
                # When output is piped/redirected, show a simple status message
                self.console.print("[dim cyan]→ Processing...[/dim cyan]", flush=True)

            # Send query (context maintained automatically)
            await client.query(user_message)

            # Receive and process ALL messages (including tool results)
            result_msg = None
            async for message in client.receive_messages():
                # Check for ResultMessage to know when to stop
                if isinstance(message, ResultMessage):
                    result_msg = message
                    break

                message_has_text = False
                message_has_tools = False

                if hasattr(message, "content"):
                    for block in message.content:
                        # Text content
                        if hasattr(block, "text"):
                            if spinner and spinner.is_started:
                                spinner.stop()
                                # Print header when we start getting text
                                if not response_text:
                                    self.console.print()
                                    self.console.print("[dim]─────────────────────────────────────────[/dim]")
                                    self.console.print("[bold cyan]Uatu:[/bold cyan]")
                                    self.console.print()

                            # Render each text block as markdown and stream it
                            md = LeftAlignedMarkdown(block.text)
                            self.console.print(md)
                            response_text += block.text
                            message_has_text = True

                        # Tool usage (when Claude calls a tool)
                        elif hasattr(block, "name") and hasattr(block, "input"):
                            if spinner and spinner.is_started:
                                spinner.stop()

                            message_has_tools = True
                            tool_name = block.name
                            tool_input = block.input if hasattr(block, "input") else None

                            # Track tool_use_id for matching results later
                            if hasattr(block, "id"):
                                self.tool_use_map[block.id] = tool_name

                            # Show tool usage with enhanced display
                            self.renderer.show_tool_usage(tool_name, tool_input)

                        # Tool result (when tool execution completes)
                        # These come in UserMessage blocks via receive_messages()
                        elif hasattr(block, "tool_use_id") and hasattr(block, "content"):
                            # Show tool result preview if enabled
                            if self.settings.uatu_show_tool_previews:
                                tool_use_id = block.tool_use_id
                                tool_response = block.content

                                # Look up the tool name from our tracking map
                                tool_name = self.tool_use_map.get(tool_use_id, "unknown")

                                # Show the preview
                                self.renderer.show_tool_result(tool_name, tool_response)

                # Restart spinner after tools (waiting for next response)
                if message_has_tools and not message_has_text:
                    self.console.print()  # Breathing room
                    if spinner and not spinner.is_started:
                        spinner.start()

            # Update stats from result message
            if result_msg:
                self.stats.update_from_result(result_msg)

            # Display closing and stats (text was already streamed)
            if response_text:
                self.console.print()
                self.console.print()
                self.console.print("[dim]─────────────────────────────────────────[/dim]")

                # Show stats at bottom if enabled
                if self.settings.uatu_show_stats and self.stats.conversation_turns > 0:
                    from rich.panel import Panel
                    from rich.text import Text

                    stats_content = Text(self.stats.format_compact(), style="cyan")
                    stats_panel = Panel.fit(
                        stats_content,
                        border_style="dim cyan",
                        padding=(0, 1),
                        title="[dim]Session[/dim]",
                        title_align="left",
                    )
                    self.console.print()
                    self.console.print(stats_panel)

                self.console.print()

        except Exception as e:
            self.renderer.error(str(e))
        finally:
            if spinner and spinner.is_started:
                spinner.stop()
