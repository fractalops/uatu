"""Slash command handling for chat interface."""

from datetime import datetime
from typing import Literal

from rich.console import Console

from uatu.permissions import PermissionHandler

# Command result type
CommandResult = Literal["continue", "exit", "clear"]


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

    def handle_command(self, command: str) -> CommandResult:
        """Handle a slash command.

        Args:
            command: The slash command (e.g., "/help", "/exit")

        Returns:
            Command result: "continue", "exit", or "clear"
        """
        if command == "/exit" or command == "/quit":
            self.console.print("[yellow]Goodbye![/yellow]")
            return "exit"

        if command == "/help":
            self._show_help()
            return "continue"

        if command in ("/clear", "/reset"):
            label_map = {
                "/clear": "Clearing conversation context...",
                "/reset": "Resetting conversation context...",
            }
            label = label_map.get(command, "Resetting conversation context...")
            self.console.print(f"[cyan]✓ {label}[/cyan]")
            return "clear"

        if command in ("/recover", "/rewind"):
            self.console.print("[cyan]✓ Recovering last summary and resetting context...[/cyan]")
            return "recover"

        if command.startswith("/allowlist"):
            self._handle_allowlist(command)
            return "continue"

        if command in ("/interrupt", "/stop"):
            # Interrupt is handled in ChatSession using current client
            return "interrupt"

        if command == "/resume":
            self.console.print("[cyan]→ Suggest asking for a lighter, MCP-first plan to continue.[/cyan]")
            return "continue"

        self.console.print(f"[red]Unknown command: {command}[/red]")
        return "continue"

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
        elif parts[1] == "add" and len(parts) == 3:
            self._add_to_allowlist(parts[2])
        elif parts[1] == "clear":
            self._clear_allowlist()
        elif parts[1] == "remove" and len(parts) == 3:
            self._remove_from_allowlist(parts[2])
        else:
            self.console.print("[red]Invalid /allowlist command. Use /help for usage[/red]")

    def _show_allowlist(self) -> None:
        """Display current allowlist."""
        from uatu.ui.console import ConsoleRenderer

        entries = self.permission_handler.allowlist.get_entries()

        if not entries:
            self.console.print("[yellow]No commands in allowlist[/yellow]")
            return

        # Use minimal table for cleaner look
        renderer = ConsoleRenderer(self.console)
        table = renderer.create_minimal_table(title="Allowlisted Commands")
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

    def _add_to_allowlist(self, command: str) -> None:
        """Add command to allowlist with security validation.

        Args:
            command: Command to add
        """
        from uatu.allowlist import AllowlistManager

        # Strip surrounding quotes if present
        command = command.strip().strip('"').strip("'")

        # Security validation - reject high-risk commands
        risk_style, risk_text, warning = AllowlistManager.detect_risk_category(command)

        # Reject credential access and destructive commands
        if risk_text in ["Credential Access", "Destructive"]:
            self.console.print(f"[red]✗ Cannot add to allowlist: {risk_text}[/red]")
            self.console.print(f"[red]  {warning}[/red]")
            return

        # Warn about system modification but allow
        if risk_text == "System Modification":
            self.console.print(f"[yellow]⚠ Warning: {risk_text}[/yellow]")
            self.console.print(f"[yellow]  {warning}[/yellow]")

        # Check for blocked network commands
        base_cmd = AllowlistManager.get_base_command(command)
        if base_cmd in AllowlistManager.BLOCKED_NETWORK_COMMANDS:
            self.console.print(f"[red]✗ Cannot add network command to allowlist: {base_cmd}[/red]")
            self.console.print("[yellow]Network commands are blocked by default for security.[/yellow]")
            self.console.print("[yellow]Use UATU_ALLOW_NETWORK=true to enable network commands.[/yellow]")
            return

        # Check for suspicious patterns
        if risk_text == "Suspicious Pattern":
            self.console.print(f"[red]✗ Cannot add to allowlist: {risk_text}[/red]")
            self.console.print(f"[red]  {warning}[/red]")
            return

        # Add to allowlist
        try:
            self.permission_handler.allowlist.add_command(command)
            self.console.print(f"[green]✓ Added to allowlist: {command}[/green]")

            # Show what was actually added
            entries = self.permission_handler.allowlist.get_entries()
            latest = entries[-1] if entries else None
            if latest:
                entry_type = latest.get("type", "exact")
                pattern = latest.get("pattern", command)
                self.console.print(f"[dim]  Pattern: {pattern} (type: {entry_type})[/dim]")
        except ValueError as e:
            self.console.print(f"[red]✗ Error: {e}[/red]")

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
