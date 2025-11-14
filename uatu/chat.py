"""Interactive chat interface for Uatu."""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style as PromptStyle
from rich import box
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.markdown import Heading as RichHeading
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from uatu.allowlist import AllowlistManager
from uatu.config import get_settings
from uatu.permissions import PermissionHandler
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

        # Initialize permission handler with allowlist
        self.permission_handler = PermissionHandler()
        # Inject UI callback for getting approvals
        self.permission_handler.get_approval_callback = self._get_inline_approval

        # Custom system prompt optimized for system troubleshooting
        system_prompt = """You are Uatu, The Watcher - an expert system troubleshooting agent.

Your role is to:
1. Observe system state using available tools
2. Identify patterns and anomalies
3. Diagnose root causes
4. Provide actionable recommendations with risk assessment

Available Tools:
- **Bash**: Your primary tool for system investigation. Use ps, top, df, netstat, lsof, etc.
- **MCP tools**: Specialized monitoring tools (get_system_info, list_processes, etc.)
  - Use these as fallbacks if bash commands fail or are unavailable

Note on Read-Only Mode:
- If you see "Bash commands disabled by UATU_READ_ONLY", the system is in read-only mode
- In read-only mode, use the MCP tools instead
- Always respect the security settings - don't repeatedly try bash if it's blocked

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
        from claude_agent_sdk import HookMatcher

        self.options = ClaudeAgentOptions(
            model=self.settings.uatu_model,
            # Use custom system prompt optimized for system troubleshooting
            system_prompt=system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
            max_turns=20,  # Allow more back-and-forth in chat mode
            # Allow all MCP system tools (they're read-only) and Bash
            # Bash will be controlled by our hook and UATU_READ_ONLY setting
            allowed_tools=[
                "mcp__system-tools__get_system_info",
                "mcp__system-tools__list_processes",
                "mcp__system-tools__get_process_tree",
                "mcp__system-tools__find_process_by_name",
                "mcp__system-tools__check_port_binding",
                "mcp__system-tools__read_proc_file",
                "Bash",  # Built-in Bash tool (gated by permission hook)
            ],
            # Use hooks for permission control on Bash commands
            hooks={"PreToolUse": [HookMatcher(hooks=[self.permission_handler.pre_tool_use_hook])]},
            # Capture stderr for debugging
            stderr=lambda msg: self.console.print(f"[dim red]SDK: {msg}[/dim red]"),
        )

    def _render_approval_options(self, selected_index: int, command: str) -> Text:
        """Render approval options with current selection highlighted."""
        options = Text()

        # Allow option
        if selected_index == 0:
            options.append("  → ", style="green bold")
            options.append("Allow\n", style="green")
        else:
            options.append("  ○ ", style="dim")
            options.append("Allow\n", style="dim")

        # Always allow option - show what will be allowlisted
        base_cmd = AllowlistManager.get_base_command(command)
        if base_cmd in AllowlistManager.SAFE_BASE_COMMANDS:
            always_text = f"Always allow '{base_cmd}'\n"
        else:
            always_text = "Always allow (exact)\n"

        if selected_index == 1:
            options.append("  → ", style="cyan bold")
            options.append(always_text, style="cyan")
        else:
            options.append("  ○ ", style="dim")
            options.append(always_text, style="dim")

        # Deny option
        if selected_index == 2:
            options.append("  → ", style="red bold")
            options.append("Deny\n", style="red")
        else:
            options.append("  ○ ", style="dim")
            options.append("Deny\n", style="dim")

        options.append("\n(Use ↑↓ arrow keys, Enter to confirm)", style="dim")
        return options

    async def _get_inline_approval(self, description: str, command: str) -> tuple[bool, bool]:
        """Get user approval with inline arrow-key navigation and live updates.

        Returns:
            Tuple of (approved, add_to_allowlist)
        """
        import threading
        import time

        from prompt_toolkit.application import Application
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.widgets import Label

        # Show command details (static part)
        self.console.print()
        self.console.print("[yellow][!] Bash command requested[/yellow]")
        if description:
            self.console.print(f"[dim]{description}[/dim]")
        self.console.print(f"[dim]Command: {command}[/dim]")
        self.console.print()

        # Track selection state
        selected = [2]  # Start with "Deny" (index 2)
        running = [True]  # Track if we're still running

        # Create key bindings for arrow navigation
        kb = KeyBindings()

        @kb.add(Keys.Up)
        def _(event):
            selected[0] = max(0, selected[0] - 1)

        @kb.add(Keys.Down)
        def _(event):
            selected[0] = min(2, selected[0] + 1)

        @kb.add(Keys.Enter)
        def _(event):
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("c-c")  # Ctrl+C
        def _(event):
            running[0] = False
            event.app.exit(result=2)  # Deny on cancel

        # Create minimal application for key capture
        app = Application(
            layout=Layout(Label("")),
            key_bindings=kb,
            full_screen=False,
            mouse_support=False,
        )

        # Use Rich Live to update the selection display
        with Live(
            self._render_approval_options(selected[0], command),
            console=self.console,
            refresh_per_second=20,
        ) as live:
            # Run app in a separate thread and update display
            def run_app():
                return app.run()

            def update_display():
                """Continuously update the display while running."""
                while running[0]:
                    live.update(self._render_approval_options(selected[0], command))
                    time.sleep(0.05)  # Update every 50ms

            # Run app and update loop concurrently
            update_thread = threading.Thread(target=update_display, daemon=True)
            update_thread.start()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, run_app)

            # Stop the update thread
            running[0] = False
            update_thread.join(timeout=0.5)

        # 0 = Allow, 1 = Always allow, 2 = Deny
        approved = result in [0, 1]
        add_to_allowlist = result == 1
        return (approved, add_to_allowlist)

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

                                # Bash commands: Show description + command
                                if tool_name == "Bash" and hasattr(block, "input"):
                                    tool_input = block.input
                                    command = tool_input.get("command", "")
                                    description = tool_input.get("description", "")

                                    # Show description as header if available
                                    if description:
                                        self.console.print(f"[dim]→ {description}[/dim]")

                                    # Always show the actual command
                                    cmd_preview = command[:120]
                                    if len(command) > 120:
                                        cmd_preview += "..."
                                    self.console.print(f"[dim]  $ {cmd_preview}[/dim]")

                                # MCP tools: Show with MCP prefix and parameters
                                elif tool_name.startswith("mcp__"):
                                    # Clean up name: mcp__system-tools__get_system_info -> Get System Info
                                    clean_name = tool_name.split("__")[-1].replace("_", " ").title()
                                    self.console.print(f"[dim]→ MCP: {clean_name}[/dim]")

                                    # Show key parameters if available
                                    if hasattr(block, "input"):
                                        tool_input = block.input
                                        if tool_input:
                                            # Show first 3 parameters
                                            params = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:3])
                                            if params:
                                                self.console.print(f"[dim]   ({params})[/dim]")

                                # Other tools: Simple display
                                else:
                                    self.console.print(f"[dim]→ {tool_name}[/dim]")

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
            style=PromptStyle.from_dict({"prompt": "ansicyan bold"}),
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
                                    "/help             - Show this help message\n"
                                    "/exit             - Exit the chat\n"
                                    "/allowlist        - Show allowlisted commands\n"
                                    "/allowlist clear  - Clear all allowlist entries\n"
                                    "/allowlist remove <pattern> - Remove a specific entry\n\n"
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
                        elif user_input.startswith("/allowlist"):
                            parts = user_input.split(maxsplit=2)
                            if len(parts) == 1:
                                # Show allowlist
                                entries = self.permission_handler.allowlist.get_entries()
                                if not entries:
                                    self.console.print("[yellow]No commands in allowlist[/yellow]")
                                else:
                                    from rich.table import Table

                                    table = Table(title="Allowlisted Commands", border_style="cyan")
                                    table.add_column("Pattern", style="green")
                                    table.add_column("Type", style="dim")
                                    table.add_column("Added", style="dim")

                                    for entry in entries:
                                        pattern = entry.get("pattern", "")
                                        entry_type = entry.get("type", "")
                                        added = entry.get("added", "")
                                        # Format date if present
                                        if added:
                                            try:
                                                from datetime import datetime

                                                dt = datetime.fromisoformat(added)
                                                added = dt.strftime("%Y-%m-%d %H:%M")
                                            except ValueError:
                                                pass
                                        table.add_row(pattern, entry_type, added)

                                    self.console.print(table)
                            elif parts[1] == "clear":
                                self.permission_handler.allowlist.clear()
                                self.console.print("[green]Allowlist cleared[/green]")
                            elif parts[1] == "remove" and len(parts) == 3:
                                pattern = parts[2]
                                if self.permission_handler.allowlist.remove_command(pattern):
                                    self.console.print(f"[green]Removed '{pattern}' from allowlist[/green]")
                                else:
                                    self.console.print(f"[yellow]Pattern '{pattern}' not found in allowlist[/yellow]")
                            else:
                                self.console.print("[red]Invalid /allowlist command. Use /help for usage[/red]")
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
        self.console.print("[dim]Commands: /help, /exit, /allowlist[/dim]")
        self.console.print("[dim]Context is maintained across messages - follow-up questions work![/dim]")
        self.console.print("[dim]Tip: Use 'Always allow' to skip permission prompts for trusted commands[/dim]")
        self.console.print()

        # Run async chat loop
        asyncio.run(self._run_async())
