"""Message and streaming response handlers."""

import asyncio
import sys
import time

from claude_agent_sdk import ClaudeSDKClient, ResultMessage
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

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
        self.stats.max_budget_usd = self.settings.uatu_max_budget_usd
        # Live turn telemetry
        self.turn_start_ts: float | None = None
        self.turn_tool_count: int = 0
        self.turn_last_tool: str | None = None
        # Track per-tool timing
        self.tool_start_ts: dict[str, float] = {}
        # Optional prompt refresher (set by ChatSession)
        self.refresh_prompt: callable | None = None

    def _print_stats_line(self) -> None:
        """Print a lightweight inline stats line if enabled."""
        if (
            self.settings.uatu_show_stats
            and self.stats.conversation_turns > 0
            and sys.stdout.isatty()
        ):
            self.console.print(f"[dim cyan]{self.stats.format_compact()}[/dim cyan]")

    async def _refresh_loop(
        self,
        stop_event: asyncio.Event,
        interval: float = 0.5,
        spinner_obj: Spinner | None = None,
    ) -> None:
        """Periodically refresh prompt/spinner to show live stats."""
        while not stop_event.is_set():
            if spinner_obj:
                elapsed = 0.0
                if self.turn_start_ts is not None:
                    elapsed = time.monotonic() - self.turn_start_ts
                spinner_text = Text("Pondering... ", style="cyan")
                spinner_text.append(f"{elapsed:0.1f}s", style="dim")
                if self.turn_tool_count:
                    spinner_text.append(f" · tools:{self.turn_tool_count}", style="dim")
                if self.turn_last_tool:
                    spinner_text.append(f" · last:{self.turn_last_tool}", style="dim")
                # Live tokens/cost are only available at ResultMessage; show placeholder
                if self.settings.uatu_show_stats:
                    if self.stats.max_budget_usd and self.stats.total_cost_usd:
                        remaining = max(self.stats.max_budget_usd - self.stats.total_cost_usd, 0)
                        spinner_text.append(f" · budget:${remaining:.4f}", style="dim")
                    spinner_text.append(" · tokens:...", style="dim")
                spinner_obj.text = spinner_text
            if self.refresh_prompt:
                try:
                    self.refresh_prompt()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                continue

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
        spinner_obj: Spinner | None = None
        has_tty_output = sys.stdout.isatty()
        stop_event: asyncio.Event | None = None
        tick_task: asyncio.Task | None = None

        try:
            # Show progress indicator - spinner for TTY output, simple message otherwise
            if has_tty_output:
                # Reset turn telemetry
                self.turn_start_ts = time.monotonic()
                self.turn_tool_count = 0
                self.turn_last_tool = None

                stats_line = self.stats.format_compact() if self.settings.uatu_show_stats else ""
                spinner_text = Text("Pondering... ", style="cyan")
                if stats_line:
                    spinner_text.append(stats_line, style="dim")
                spinner_obj = Spinner("dots", text=spinner_text)
                live = Live(
                    spinner_obj,
                    console=self.renderer.console,
                    refresh_per_second=12,
                    transient=True,
                )
                live.start()
                spinner = live
                # Periodically refresh rprompt stats while thinking
                stop_event = asyncio.Event()
                tick_task = asyncio.create_task(self._refresh_loop(stop_event, spinner_obj=spinner_obj))
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
                            # Update telemetry
                            self.turn_tool_count += 1
                            self.turn_last_tool = tool_name
                            start_ts = time.monotonic()

                            # Track tool_use_id for matching results later
                            if hasattr(block, "id"):
                                self.tool_use_map[block.id] = tool_name
                                self.tool_start_ts[block.id] = start_ts

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
                                # Timing: show elapsed if we tracked start
                                elapsed_msg = ""
                                start_ts = self.tool_start_ts.pop(tool_use_id, None)
                                if start_ts:
                                    elapsed = time.monotonic() - start_ts
                                    elapsed_msg = f" [{elapsed:0.1f}s]"

                                # Show the preview
                                self.renderer.show_tool_result(tool_name, tool_response)
                                if elapsed_msg:
                                    pretty_name = self.renderer.clean_tool_name(tool_name)
                                    msg = f"{pretty_name} finished{elapsed_msg}"
                                    self.renderer.status(msg, status="info", dim=True)

                # Restart spinner after tools (waiting for next response)
                if message_has_tools and not message_has_text:
                    self.console.print()  # Breathing room
                    if spinner and not spinner.is_started:
                        spinner.start()

            # Update stats from result message
            if result_msg:
                self.stats.update_from_result(result_msg)
                if self.refresh_prompt:
                    self.refresh_prompt()
                # Show updated stats after completion
                self._print_stats_line()

            # Display closing and stats (text was already streamed)
            if response_text:
                self.console.print()

            # Show stats at bottom if enabled and we have at least one turn
            # (Inline stats lines removed to keep transcript clean; rprompt shows stats)

        except Exception as e:
            self.renderer.error(str(e))
        finally:
            if stop_event:
                stop_event.set()
            if tick_task:
                try:
                    await tick_task
                except Exception:
                    pass
            if spinner and spinner.is_started:
                spinner.stop()
            if spinner and not has_tty_output:
                # In non-tty mode we print a newline to separate output
                self.console.print()
