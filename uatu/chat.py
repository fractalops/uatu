"""Interactive chat interface for Uatu."""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.markdown import Heading as RichHeading
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.spinner import Spinner
from rich.text import Text

from uatu.config import get_settings
from uatu.tools import create_system_tools_mcp_server


class LeftAlignedHeading(RichHeading):
    """Heading that's left-aligned instead of centered."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"  # Changed from "center"
        if self.tag == "h1":
            # Draw a border around h1s
            yield Panel(
                text,
                box=box.HEAVY,
                style="markdown.h1.border",
            )
        else:
            # Styled text for h2 and beyond
            if self.tag == "h2":
                yield Text("")
            yield text


class LeftAlignedMarkdown(RichMarkdown):
    """Markdown renderer with left-aligned headings."""

    elements = RichMarkdown.elements.copy()
    elements["heading_open"] = LeftAlignedHeading


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

        # Store options for creating client
        # Note: API key is read from ANTHROPIC_API_KEY environment variable by SDK
        self.options = ClaudeAgentOptions(
            model=self.settings.uatu_model,
            system_prompt=self.system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
            max_turns=20,  # Allow more back-and-forth in chat mode
            permission_mode="default",  # Use custom handler for permissions
            can_use_tool=self._permission_handler,  # Custom handler for Bash commands
        )

    async def _permission_handler(self, tool_name: str, tool_input: dict, context: dict) -> dict:
        """Handle tool permissions - ask approval for Bash commands."""
        # Only prompt for Bash commands - everything else is read-only monitoring
        # Note: MCP tools come through as "mcp__server-name__tool-name"
        if tool_name == "Bash" or "bash" in tool_name.lower():
            command = tool_input.get("command", "")
            description = tool_input.get("description", "")

            # Show command details
            self.console.print()
            self.console.print("[yellow][!] Bash command requested[/yellow]")
            if description:
                self.console.print(f"[dim]{description}[/dim]")
            self.console.print(f"[dim]Command: {command}[/dim]")
            self.console.print()

            # Show inline yes/no prompt (y/n)
            loop = asyncio.get_event_loop()
            approved = await loop.run_in_executor(
                None, lambda: Confirm.ask("Allow this command?", console=self.console, default=False)
            )

            if not approved:
                self.console.print("[red][x] Command denied[/red]")
                return {"behavior": "deny", "message": "User declined to execute bash command"}

            self.console.print("[green][+] Command allowed[/green]")

        return {"behavior": "allow"}

    async def _handle_message(self, client: ClaudeSDKClient, user_message: str) -> None:
        """Handle a user message and generate response."""
        response_text = ""
        first_response = True

        try:
            # Send query (context is maintained automatically)
            await client.query(user_message)

            # Show spinner while waiting for response
            with Live(
                Spinner("dots", text="Thinking...", style="cyan"),
                console=self.console,
                transient=True,
            ) as live:
                # Receive response
                async for message in client.receive_response():
                    # Stop spinner on first response
                    if first_response:
                        live.stop()
                        first_response = False

                    if hasattr(message, "content"):
                        for block in message.content:
                            if hasattr(block, "text"):
                                response_text += block.text
                            # Show tool usage if present
                            elif hasattr(block, "name"):
                                tool_name = block.name
                                # For Bash commands, show what's being executed
                                if tool_name == "Bash" and hasattr(block, "input"):
                                    tool_input = block.input
                                    command = tool_input.get("command", "")
                                    description = tool_input.get("description", "")

                                    # Show description as header if available
                                    if description:
                                        self.console.print(f"[dim]-> {description}[/dim]")

                                    # Always show the actual command
                                    cmd_preview = command[:120]
                                    if len(command) > 120:
                                        cmd_preview += "..."
                                    self.console.print(f"[dim]  $ {cmd_preview}[/dim]")
                                else:
                                    self.console.print(f"[dim]-> Using tool: {tool_name}[/dim]")

            # Display response
            if response_text:
                self.console.print()
                # Use custom markdown renderer with left-aligned headings
                md = LeftAlignedMarkdown(response_text)
                self.console.print(md)
                self.console.print()
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    async def _run_async(self) -> None:
        """Async chat loop with long-lived client."""
        # Setup prompt session
        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            style=Style.from_dict({"prompt": "ansicyan bold"}),
        )

        # Create long-lived client that maintains conversation context
        async with ClaudeSDKClient(self.options) as client:
            while True:
                try:
                    # Get user input (run in executor to avoid blocking async loop)
                    loop = asyncio.get_event_loop()
                    user_input = await loop.run_in_executor(None, session.prompt, "You: ")

                    if not user_input.strip():
                        continue

                    # Handle special commands
                    if user_input.startswith("/"):
                        if user_input == "/exit" or user_input == "/quit":
                            self.console.print("[yellow]Goodbye![/yellow]")
                            break
                        elif user_input == "/clear":
                            self.console.print("[yellow]/clear not supported - restart chat to clear context[/yellow]")
                            continue
                        elif user_input == "/help":
                            self.console.print(
                                Panel(
                                    "[bold]Available Commands:[/bold]\n\n"
                                    "/help  - Show this help message\n"
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
                    await self._handle_message(client, user_input)

                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Use /exit to quit[/yellow]")
                    continue
                except EOFError:
                    break
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/red]")
                    continue

    def run(self) -> None:
        """Run the interactive chat loop."""
        # Welcome message
        self.console.print(
            Panel.fit(
                "[bold blue]Uatu - The Watcher[/bold blue]\n[dim]Interactive System Troubleshooting Assistant[/dim]",
                border_style="blue",
            )
        )
        self.console.print()
        self.console.print("[dim]Commands: /help, /exit[/dim]")
        self.console.print("[dim]Context is maintained across messages - follow-up questions work![/dim]")
        self.console.print()

        # Run async chat loop
        asyncio.run(self._run_async())
