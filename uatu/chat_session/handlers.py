"""Message and streaming response handlers."""

from claude_agent_sdk import ClaudeSDKClient
from rich.console import Console

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

    async def handle_message(self, client: ClaudeSDKClient, user_message: str) -> None:
        """Handle a user message and stream response.

        Args:
            client: Claude SDK client
            user_message: User's message
        """
        response_text = ""
        spinner = None

        try:
            # Create spinner for thinking
            spinner = self.renderer.create_spinner("Pondering...")
            spinner.start()

            # Send query (context maintained automatically)
            await client.query(user_message)

            # Receive and process streaming response
            async for message in client.receive_response():
                message_has_text = False
                message_has_tools = False

                if hasattr(message, "content"):
                    for block in message.content:
                        # Text content
                        if hasattr(block, "text"):
                            if spinner and spinner.is_started:
                                spinner.stop()
                            response_text += block.text
                            message_has_text = True

                        # Tool usage
                        elif hasattr(block, "name"):
                            if spinner and spinner.is_started:
                                spinner.stop()

                            message_has_tools = True
                            tool_name = block.name
                            tool_input = block.input if hasattr(block, "input") else None

                            # Show tool usage with enhanced display
                            self.renderer.show_tool_usage(tool_name, tool_input)

                # Restart spinner after tools (waiting for next response)
                if message_has_tools and not message_has_text:
                    self.console.print()  # Breathing room
                    if spinner and not spinner.is_started:
                        spinner.start()

            # Display final response
            if response_text:
                self.console.print()
                # Add visual separator and label
                self.console.print("[dim]─────────────────────────────────────────[/dim]")
                self.console.print("[bold cyan]Uatu:[/bold cyan]")
                self.console.print()
                md = LeftAlignedMarkdown(response_text)
                self.console.print(md)
                self.console.print()
                self.console.print("[dim]─────────────────────────────────────────[/dim]")
                self.console.print()

        except Exception as e:
            self.renderer.error(str(e))
        finally:
            if spinner and spinner.is_started:
                spinner.stop()
