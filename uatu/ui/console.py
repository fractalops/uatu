"""Reusable console UI components and utilities."""

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

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

    def show_welcome(
        self,
        subagents_enabled: bool = False,
        read_only: bool = True,
        allow_network: bool = False,
        require_approval: bool = True,
    ) -> None:
        """Show welcome message for interactive chat.

        Args:
            subagents_enabled: Whether specialized diagnostic agents are enabled
            read_only: Whether the session is in read-only mode
            allow_network: Whether network commands are allowed
            require_approval: Whether user approvals are required for risky actions
        """
        self.console.print(
            Panel.fit(
                "[bold blue]Uatu [/bold blue]\n[dim]Your Interactive System Troubleshooting Assistant[/dim]",
                border_style="blue",
            )
        )
        self.console.print()
        self.console.print("[dim]Commands: /help, /exit, /clear, /reset, /recover (coming soon), /allowlist[/dim]")
        self.console.print("[dim]Context persists across turns; follow-ups work.[/dim]")
        if require_approval:
            self.console.print("[dim]Approvals: 'Always allow' skips prompts for trusted commands.[/dim]")
        else:
            self.console.print("[dim]Approvals: disabled (auto-allow; safety filters still enforced).[/dim]")

        # Mode indicators
        ro_text = "Read-only mode: ON" if read_only else "Read-only mode: OFF (writes allowed)"
        net_text = "Network commands: ALLOWED" if allow_network else "Network commands: BLOCKED"
        self.console.print(f"[dim]{ro_text} · {net_text}[/dim]")
        self.console.print("[dim]Tools run with filters; background long scans when possible.[/dim]")

        # Show subagent status if enabled
        if subagents_enabled:
            self.console.print(
                "[dim cyan]Specialized agents: CPU/Memory, Network, I/O, Disk Space diagnostics[/dim cyan]"
            )

        self.console.print()

    def show_help(self) -> None:
        """Show help panel with available commands."""
        self.console.print(
            Panel(
                "[bold]Available Commands:[/bold]\n\n"
                "/help             - Show this help message\n"
                "/exit             - Exit the chat\n"
                "/clear            - Clear conversation context (start fresh)\n"
                "/reset            - Reset conversation context (alias for /clear)\n"
                "/recover          - (coming soon) restore conversation to a prior point\n"
                "/allowlist        - Show allowlisted commands\n"
                "/allowlist add <command> - Add a command to allowlist\n"
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

    def status(self, message: str, status: str = "info", dim: bool = False) -> None:
        """Print a status message with indicator.

        Args:
            message: Status message
            status: Type of status (success, error, warning, info)
            dim: If true, render the message dimmed
        """
        icons = {
            "success": ("✓", "green"),
            "error": ("✗", "red"),
            "warning": ("!", "yellow"),
            "info": ("→", "cyan"),
        }

        icon, color = icons.get(status, ("→", "cyan"))
        content = message if not dim else f"[dim]{message}[/dim]"
        self.console.print(f"[{color}]{icon}[/{color}] {content}")

    @staticmethod
    def clean_tool_name(tool_name: str) -> str:
        """Produce a friendly tool name for display."""
        if tool_name.startswith("mcp__"):
            return tool_name.split("__")[-1].replace("_", " ").title()
        if tool_name.startswith("safe-hints__"):
            return tool_name.split("__")[-1].replace("_", " ").title()
        return tool_name

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

            # Surface a lightweight safety hint for potentially slow scans
            slow_patterns = ("du -sh", "find ", "nc -z", "du --max-depth")
            if any(pat in command for pat in slow_patterns):
                self.console.print("[dim yellow]  ↳ Consider run_in_background=true for slow scans[/dim yellow]")

        # MCP tools: Show with MCP prefix and parameters
        elif tool_name.startswith("mcp__"):
            clean_name = self.clean_tool_name(tool_name)
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
            self.console.print(f"[dim]→ {self.clean_tool_name(tool_name)}[/dim]")

    def show_text(self, text: str) -> None:
        """Render assistant text, preferring structured layout if detected."""
        if not self._render_structured(text):
            from uatu.ui.markdown import LeftAlignedMarkdown

            md = LeftAlignedMarkdown(text)
            self.console.print(md)

    def _render_structured(self, text: str) -> bool:
        """Try to render Conclusion/Evidence/Next steps as panels. Return True if handled."""
        sections: dict[str, list[str]] = {"conclusion": [], "evidence": [], "next": []}
        current = None

        for line in text.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("conclusion"):
                current = "conclusion"
                continue
            if lower.startswith("evidence"):
                current = "evidence"
                continue
            if lower.startswith("next steps") or lower.startswith("next"):
                current = "next"
                continue
            if current:
                sections[current].append(line)

        has_structured = any(sections.values())
        if not has_structured:
            return False

        if sections["conclusion"]:
            content = "\n".join(sections["conclusion"]).strip()
            if content:
                self.console.print(Panel.fit(content, title="Conclusion", border_style="green"))

        if sections["evidence"]:
            content = "\n".join(sections["evidence"]).strip()
            if content:
                self.console.print(Panel(content, title="Evidence", border_style="cyan"))

        if sections["next"]:
            content = "\n".join(sections["next"]).strip()
            if content:
                self.console.print(Panel(content, title="Next Steps", border_style="yellow"))

        return True

    def show_tool_result(self, tool_name: str, tool_response: Any) -> None:
        """Display tool result preview.

        Args:
            tool_name: Name of the tool that was executed
            tool_response: The tool's response data
        """
        preview = ToolPreviewFormatter.format_preview(tool_name, tool_response)
        if preview:
            # Use smaller, dimmer font for previews (helps with long table output)
            # Split on newlines to apply dim style to each line
            lines = preview.split('\n')
            for line in lines:
                self.console.print(f"[dim]  {line}[/dim]")
        return preview

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

    def create_minimal_table(
        self,
        title: str | None = None,
        title_style: str = "bold cyan",
        show_header: bool = True,
    ) -> Table:
        """Create a minimal table with no borders.

        This creates a clean, scannable table without heavy borders,
        perfect for displaying lists of data like processes, allowlists, etc.

        Args:
            title: Optional table title
            title_style: Style for the title
            show_header: Whether to show column headers

        Returns:
            A minimal Rich Table ready for adding columns and rows

        Example:
            table = renderer.create_minimal_table("Processes")
            table.add_column("PID", style="cyan", no_wrap=True)
            table.add_column("Memory", justify="right")
            table.add_column("Command")
            table.add_row("1234", "2.3GB", "python app.py")
            console.print(table)
        """
        return Table(
            title=title,
            title_style=title_style,
            show_header=show_header,
            show_edge=False,  # No outer border
            show_lines=False,  # No lines between rows
            box=None,  # No box drawing characters
            padding=(0, 1),  # Minimal padding: no vertical, 1 space horizontal
        )
