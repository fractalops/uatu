"""Slash command handling for chat interface."""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from uatu.permissions import PermissionHandler


class SlashCommandHandler:
    """Handles slash commands in chat mode."""

    def __init__(self, permission_handler: PermissionHandler, console: Console):
        """Initialize command handler.

        Args:
            permission_handler: Permission handler for allowlist operations
            console: Rich console for output
        """
        self.permission_handler = permission_handler
        self.console = console

    def handle_command(self, command: str) -> bool:
        """Handle a slash command.

        Args:
            command: The slash command (e.g., "/help", "/exit")

        Returns:
            True if command was handled, False if should exit
        """
        if command == "/exit" or command == "/quit":
            self.console.print("[yellow]Goodbye![/yellow]")
            return False

        if command == "/help":
            self._show_help()
            return True

        if command == "/clear":
            self.console.print("[yellow]/clear not supported - restart chat to clear context[/yellow]")
            return True

        if command.startswith("/allowlist"):
            self._handle_allowlist(command)
            return True

        self.console.print(f"[red]Unknown command: {command}[/red]")
        return True

    def _show_help(self) -> None:
        """Show help message."""
        from uatu.ui.console import ConsoleRenderer

        renderer = ConsoleRenderer(self.console)
        renderer.show_help()

    def _handle_allowlist(self, command: str) -> None:
        """Handle /allowlist commands.

        Args:
            command: Full command string
        """
        parts = command.split(maxsplit=2)

        if len(parts) == 1:
            self._show_allowlist()
        elif parts[1] == "clear":
            self._clear_allowlist()
        elif parts[1] == "remove" and len(parts) == 3:
            self._remove_from_allowlist(parts[2])
        else:
            self.console.print("[red]Invalid /allowlist command. Use /help for usage[/red]")

    def _show_allowlist(self) -> None:
        """Display current allowlist."""
        entries = self.permission_handler.allowlist.get_entries()

        if not entries:
            self.console.print("[yellow]No commands in allowlist[/yellow]")
            return

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
                    dt = datetime.fromisoformat(added)
                    added = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass

            table.add_row(pattern, entry_type, added)

        self.console.print(table)

    def _clear_allowlist(self) -> None:
        """Clear all allowlist entries."""
        self.permission_handler.allowlist.clear()
        self.console.print("[green]✓ Allowlist cleared[/green]")

    def _remove_from_allowlist(self, pattern: str) -> None:
        """Remove pattern from allowlist.

        Args:
            pattern: Pattern to remove
        """
        if self.permission_handler.allowlist.remove_command(pattern):
            self.console.print(f"[green]✓ Removed '{pattern}' from allowlist[/green]")
        else:
            self.console.print(f"[yellow]Pattern '{pattern}' not found in allowlist[/yellow]")
