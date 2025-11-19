"""Reusable console UI components and utilities."""

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner

from uatu.tools.constants import Tools
from uatu.ui.tool_preview import ToolPreviewFormatter


class ConsoleRenderer:
    """Helper for rendering consistent UI elements."""

    def __init__(self, console: Console | None = None):
        """Initialize console renderer.

        Args:
            console: Rich console. Creates new one if not provided.
        """
        self.console = console or Console()

    def show_welcome(self) -> None:
        """Show welcome message for interactive chat."""
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

    def show_help(self) -> None:
        """Show help panel with available commands."""
        self.console.print(
            Panel(
                "[bold]Available Commands:[/bold]\n\n"
                "/help             - Show this help message\n"
                "/exit             - Exit the chat\n"
                "/clear            - Clear conversation context (start fresh)\n"
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

    def create_spinner(self, text: str = "Pondering...") -> Live:
        """Create a spinner for long-running operations.

        Args:
            text: Text to display next to spinner

        Returns:
            Live spinner context (use with .start()/.stop())
        """
        spinner = Spinner("dots", text=f"[cyan]{text}")
        return Live(spinner, console=self.console, refresh_per_second=10, transient=True)

    def status(self, message: str, status: str = "info") -> None:
        """Print a status message with indicator.

        Args:
            message: Status message
            status: Type of status (success, error, warning, info)
        """
        icons = {
            "success": ("✓", "green"),
            "error": ("✗", "red"),
            "warning": ("!", "yellow"),
            "info": ("→", "cyan"),
        }

        icon, color = icons.get(status, ("→", "cyan"))
        self.console.print(f"[{color}]{icon}[/{color}] {message}")

    def show_tool_usage(self, tool_name: str, tool_input: dict | None = None) -> None:
        """Display tool usage with consistent formatting.

        Args:
            tool_name: Name of the tool being called
            tool_input: Optional tool input parameters
        """
        # Bash commands: Show description + command
        if tool_name == Tools.BASH and tool_input:
            command = tool_input.get("command", "")
            description = tool_input.get("description", "")

            if description:
                self.console.print(f"[dim]→ {description}[/dim]")

            cmd_preview = command[:120]
            if len(command) > 120:
                cmd_preview += "..."
            self.console.print(f"[dim]  $ {cmd_preview}[/dim]")

        # MCP tools: Show with MCP prefix and parameters
        elif tool_name.startswith("mcp__"):
            clean_name = tool_name.split("__")[-1].replace("_", " ").title()
            self.console.print(f"[dim]→ MCP: {clean_name}[/dim]")

            if tool_input:
                params = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:3])
                if params:
                    self.console.print(f"[dim]   ({params})[/dim]")

        # Network tools: Show with spinner indicator
        elif Tools.is_network_tool(tool_name):
            self.console.print(f"[dim]→ {tool_name}[/dim]")
            if tool_input:
                url_or_query = tool_input.get("url") or tool_input.get("query", "")
                if url_or_query:
                    preview = url_or_query[:80]
                    if len(url_or_query) > 80:
                        preview += "..."
                    self.console.print(f"[dim]   {preview}[/dim]")

        # Other tools
        else:
            self.console.print(f"[dim]→ {tool_name}[/dim]")

    def show_tool_result(self, tool_name: str, tool_response: Any) -> None:
        """Display tool result preview.

        Args:
            tool_name: Name of the tool that was executed
            tool_response: The tool's response data
        """
        preview = ToolPreviewFormatter.format_preview(tool_name, tool_response)
        if preview:
            # Indent the preview slightly for hierarchy
            self.console.print(f"[dim]  {preview}[/dim]")

    def error(self, message: str) -> None:
        """Show error message."""
        self.console.print(f"[red]Error: {message}[/red]")

    def print_panel(self, content: str, title: str = "", border_style: str = "cyan") -> None:
        """Print content in a panel.

        Args:
            content: Panel content
            title: Optional panel title
            border_style: Border color/style
        """
        self.console.print(Panel(content, title=title, border_style=border_style))
