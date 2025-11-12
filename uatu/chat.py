"""Interactive chat interface for Uatu."""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel

from uatu.config import get_settings
from uatu.tools import create_system_tools_mcp_server


class UatuChat:
    """Interactive chat interface for Uatu."""

    def __init__(self) -> None:
        """Initialize the chat interface."""
        self.settings = get_settings()
        self.console = Console()

        # System prompt
        self.system_prompt = """You are Uatu, The Watcher - an expert system troubleshooting agent.

Your role is to:
1. Observe system state using available tools
2. Identify patterns and anomalies
3. Diagnose root causes
4. Provide actionable recommendations with risk assessment

When analyzing issues:
- Look for common patterns: crash loops, port conflicts, zombie processes, resource exhaustion
- Consider parent-child process relationships
- Correlate multiple signals (CPU, memory, process counts)
- Explain your reasoning clearly
- Cite specific evidence (PIDs, process names, resource usage)

Communication style:
- Be conversational and helpful
- Use markdown for formatting
- Be concise but thorough
- Ask clarifying questions if needed
- Focus on actionable insights

Remember: You're in an interactive chat. Users can ask follow-up questions, request more details,
or ask you to investigate related issues."""

        # Create SDK client with MCP server
        options = ClaudeAgentOptions(
            api_key=self.settings.anthropic_api_key,
            model=self.settings.uatu_model,
            max_tokens=self.settings.uatu_max_tokens,
            temperature=self.settings.uatu_temperature,
            system_prompt=self.system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
        )
        self.client = ClaudeSDKClient(options)

    async def _handle_message(self, user_message: str) -> None:
        """Handle a user message and generate response."""
        response_text = ""

        with self.console.status("[bold green]Thinking...", spinner="dots"):
            # Send query to SDK client
            await self.client.query(user_message)

            # Receive response
            async for message in self.client.receive_response():
                if hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "text"):
                            response_text += block.text
                        # Show tool usage if present
                        elif hasattr(block, "name"):
                            self.console.print(f"[dim]→ Using tool: {block.name}[/dim]")

        # Display response
        if response_text:
            self.console.print()
            # Use rich markdown rendering
            from rich.markdown import Markdown

            self.console.print(Markdown(response_text))
            self.console.print()

    def run(self) -> None:
        """Run the interactive chat loop."""
        # Welcome message
        self.console.print(
            Panel.fit(
                "[bold blue]Uatu - The Watcher[/bold blue]\n"
                "[dim]Interactive System Troubleshooting Assistant[/dim]",
                border_style="blue",
            )
        )
        self.console.print()
        self.console.print("[dim]Commands: /help, /clear, /exit[/dim]")
        self.console.print()

        # Setup prompt session
        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            style=Style.from_dict({"prompt": "ansicyan bold"}),
        )

        while True:
            try:
                # Get user input
                user_input = session.prompt("You: ")

                if not user_input.strip():
                    continue

                # Handle special commands
                if user_input.startswith("/"):
                    if user_input == "/exit" or user_input == "/quit":
                        self.console.print("[yellow]Goodbye![/yellow]")
                        break
                    elif user_input == "/clear":
                        # Reset client for new conversation
                        options = ClaudeAgentOptions(
                            api_key=self.settings.anthropic_api_key,
                            model=self.settings.uatu_model,
                            max_tokens=self.settings.uatu_max_tokens,
                            temperature=self.settings.uatu_temperature,
                            system_prompt=self.system_prompt,
                            mcp_servers={"system-tools": create_system_tools_mcp_server()},
                        )
                        self.client = ClaudeSDKClient(options)
                        self.console.clear()
                        self.console.print("[green]Conversation cleared[/green]")
                        continue
                    elif user_input == "/help":
                        self.console.print(
                            Panel(
                                "[bold]Available Commands:[/bold]\n\n"
                                "/help  - Show this help message\n"
                                "/clear - Clear conversation history\n"
                                "/exit  - Exit the chat\n\n"
                                "[bold]Example questions:[/bold]\n"
                                "• Check system health\n"
                                "• Why is CPU usage so high?\n"
                                "• Show me processes using lots of memory\n"
                                "• Are there any zombie processes?\n"
                                "• Investigate crash loops in PM2",
                                title="Help",
                                border_style="cyan",
                            )
                        )
                        continue
                    else:
                        self.console.print(f"[red]Unknown command: {user_input}[/red]")
                        continue

                # Handle regular message
                asyncio.run(self._handle_message(user_input))

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use /exit to quit[/yellow]")
                continue
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                continue
