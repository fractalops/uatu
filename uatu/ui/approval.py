"""Approval prompt UI components."""

import asyncio
import sys
import threading
import time

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.widgets import Label
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from uatu.allowlist import AllowlistManager
from uatu.network_allowlist import NetworkAllowlistManager


class ApprovalPrompt:
    """Interactive approval prompts with arrow-key navigation."""

    def __init__(self, console: Console | None = None):
        """Initialize approval prompt.

        Args:
            console: Rich console for output. Creates new one if not provided.
        """
        self.console = console or Console()
        self._approval_count = 0  # Track number of approvals in this session

    @staticmethod
    def _fallback_choice(prompt: str) -> int:
        """Fallback when interactive UI fails; auto-deny to avoid blocking."""
        # We avoid blocking stdin prompts which can hang in some terminals.
        return 2  # deny by default

    def _render_bash_approval_options(self, selected_index: int, command: str) -> Text:
        """Render bash approval options with current selection highlighted."""
        options = Text()

        # Allow option
        if selected_index == 0:
            options.append("  → ", style="green bold")
            options.append("Allow once\n", style="green")
        else:
            options.append("  ○ ", style="dim")
            options.append("Allow once\n", style="dim")

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

        options.append("\n(↑↓ / Enter or a/A/d)", style="dim")
        return options

    async def get_bash_approval(self, description: str, command: str) -> tuple[bool, bool]:
        """Get user approval for bash command with syntax highlighting.

        Args:
            description: Command description from agent
            command: The bash command to approve

        Returns:
            Tuple of (approved, add_to_allowlist)
        """
        # Check if we have a TTY - if not, we can't show interactive prompt
        if not sys.stdin.isatty():
            self.console.print()
            self.console.print("[yellow]⚠ Command requires approval but stdin is not a terminal[/yellow]")
            self.console.print(f"[dim]{description}[/dim]")
            self.console.print()
            command_display = Syntax(command, "bash", theme="monokai", background_color="default")
            self.console.print(command_display)
            self.console.print()
            self.console.print("[red]✗ Denied (no TTY for approval)[/red]")
            self.console.print("[dim]Hint: Set UATU_REQUIRE_APPROVAL=false to use allowlist in stdin mode[/dim]")
            self.console.print()
            return (False, False)

        # Increment approval counter
        self._approval_count += 1

        # Header with counter for context
        self.console.print()
        header = f"[yellow bold]⚠ Bash Command Approval Required [dim](#{self._approval_count})[/dim][/yellow bold]"
        self.console.print(header)

        # Show description if provided
        if description:
            self.console.print(f"  [dim]{description}[/dim]")

        # Detect risk category and get warning
        risk_style, risk_text, warning = AllowlistManager.detect_risk_category(command)

        # Show risk level in a more prominent box
        risk_display = f"Risk Level: [{risk_style}]{risk_text}[/{risk_style}]"
        self.console.print(f"  {risk_display}")

        # Show warning if this is a dangerous operation
        if warning:
            self.console.print(Panel.fit(
                f"[{risk_style}]{warning}[/{risk_style}]",
                title=f"[{risk_style}]⚠ Warning[/{risk_style}]",
                border_style=risk_style,
            ))

        # Show syntax-highlighted command in a panel
        command_display = Syntax(command, "bash", theme="monokai", background_color="default")
        self.console.print(Panel.fit(
            command_display,
            title="[cyan]Command to Execute[/cyan]",
            border_style="cyan",
        ))

        # Quick inline hint for hotkeys
        self.console.print("[dim]Allow once (a) | Always (A) | Deny (d)[/dim]")

        # Track selection state
        selected = [2]  # Start with "Deny" (index 2)
        running = [True]

        # Create key bindings
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

        @kb.add("a")
        def _(event):
            selected[0] = 0
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("A")
        def _(event):
            selected[0] = 1
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("d")
        def _(event):
            selected[0] = 2
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

        approval_timeout = 30.0  # seconds before auto-deny to avoid aborts

        # Use Rich Live to update the selection display
        with Live(
            self._render_bash_approval_options(selected[0], command),
            console=self.console,
            refresh_per_second=20,
        ) as live:

            def run_app():
                return app.run()

            def update_display():
                """Continuously update the display while running."""
                while running[0]:
                    live.update(self._render_bash_approval_options(selected[0], command))
                    time.sleep(0.05)

            # Run app and update loop concurrently
            update_thread = threading.Thread(target=update_display, daemon=True)
            update_thread.start()

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(loop.run_in_executor(None, run_app), timeout=approval_timeout)
            except (TimeoutError, asyncio.CancelledError):
                self.console.print(
                    f"[yellow]Approval UI timed out after {int(approval_timeout)}s; denying to stay safe.[/yellow]"
                )
                result = self._fallback_choice("")
            finally:
                # Stop the update thread
                running[0] = False
                update_thread.join(timeout=0.5)

        # 0 = Allow, 1 = Always allow, 2 = Deny
        approved = result in [0, 1]
        add_to_allowlist = result == 1

        # Show clear confirmation with status indicator
        if approved:
            if add_to_allowlist:
                base_cmd = AllowlistManager.get_base_command(command)
                if base_cmd in AllowlistManager.SAFE_BASE_COMMANDS:
                    self.console.print(f"[green bold]✓ Allowed and added '{base_cmd}' to allowlist[/green bold]")
                else:
                    self.console.print("[green bold]✓ Allowed and added exact command to allowlist[/green bold]")
            else:
                self.console.print("[green bold]✓ Allowed once[/green bold]")
        else:
            self.console.print("[red bold]✗ Denied[/red bold]")
        self.console.print()

        return (approved, add_to_allowlist)

    def _render_network_approval_options(self, selected_index: int, url: str) -> Text:
        """Render network approval options with current selection highlighted."""
        domain = NetworkAllowlistManager.extract_domain(url)
        options = Text()

        # Allow option
        if selected_index == 0:
            options.append("  → ", style="green bold")
            options.append("Allow once\n", style="green")
        else:
            options.append("  ○ ", style="dim")
            options.append("Allow once\n", style="dim")

        # Always allow option
        always_text = f"Always allow '{domain}'\n"

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

        options.append("\n(↑↓ / Enter or a/A/d)", style="dim")
        return options

    async def get_network_approval(self, tool_name: str, url: str) -> tuple[bool, bool]:
        """Get user approval for network access with enhanced UI.

        Args:
            tool_name: Name of network tool (WebFetch, WebSearch)
            url: The URL being accessed

        Returns:
            Tuple of (approved, add_to_allowlist)
        """
        domain = NetworkAllowlistManager.extract_domain(url)

        # Check if we have a TTY - if not, we can't show interactive prompt
        if not sys.stdin.isatty():
            self.console.print()
            self.console.print("[yellow]⚠ Network access requires approval but stdin is not a terminal[/yellow]")
            self.console.print(f"[dim]Tool:   {tool_name}[/dim]")
            self.console.print(f"[dim]Domain: [yellow bold]{domain}[/yellow bold][/dim]")
            self.console.print(f"[dim]URL:    {url}[/dim]")
            self.console.print()
            self.console.print("[red]✗ Denied (no TTY for approval)[/red]")
            self.console.print("[dim]Hint: Add domain to network allowlist before running in stdin mode[/dim]")
            self.console.print()
            return (False, False)

        # Increment approval counter
        self._approval_count += 1

        # Header with counter for context
        self.console.print()
        header = f"[yellow bold]⚠ Network Access Approval Required [dim](#{self._approval_count})[/dim][/yellow bold]"
        self.console.print(header)

        # Show details in a panel
        details = f"[cyan]Tool:[/cyan]   {tool_name}\n"
        details += f"[cyan]Domain:[/cyan] [yellow bold]{domain}[/yellow bold]\n"
        details += f"[cyan]URL:[/cyan]    [dim]{url if len(url) < 70 else url[:67] + '...'}[/dim]"

        self.console.print(Panel.fit(
            details,
            title="[cyan]Request Details[/cyan]",
            border_style="cyan",
        ))

        # Quick inline hint for hotkeys
        self.console.print("[dim]Allow once (a) | Always (A) | Deny (d)[/dim]")

        # Track selection state
        selected = [2]  # Start with "Deny"
        running = [True]

        # Create key bindings
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

        @kb.add("a")
        def _(event):
            selected[0] = 0
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("A")
        def _(event):
            selected[0] = 1
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("d")
        def _(event):
            selected[0] = 2
            running[0] = False
            event.app.exit(result=selected[0])

        @kb.add("c-c")
        def _(event):
            running[0] = False
            event.app.exit(result=2)

        # Create minimal application
        app = Application(
            layout=Layout(Label("")),
            key_bindings=kb,
            full_screen=False,
            mouse_support=False,
        )

        approval_timeout = 30.0  # seconds before auto-deny to avoid aborts

        # Live update loop
        with Live(
            self._render_network_approval_options(selected[0], url),
            console=self.console,
            refresh_per_second=20,
        ) as live:

            def run_app():
                return app.run()

            def update_display():
                while running[0]:
                    live.update(self._render_network_approval_options(selected[0], url))
                    time.sleep(0.05)

            update_thread = threading.Thread(target=update_display, daemon=True)
            update_thread.start()

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(loop.run_in_executor(None, run_app), timeout=approval_timeout)
            except (TimeoutError, asyncio.CancelledError):
                timeout_msg = (
                    f"Network approval UI timed out after {int(approval_timeout)}s; denying to stay safe."
                )
                self.console.print(f"[yellow]{timeout_msg}[/yellow]")
                result = self._fallback_choice("")
            finally:
                running[0] = False
                update_thread.join(timeout=0.5)

        # 0 = Allow, 1 = Always allow, 2 = Deny
        approved = result in [0, 1]
        add_to_allowlist = result == 1

        # Show confirmation with status indicator
        if approved:
            if add_to_allowlist:
                self.console.print(f"[green bold]✓ Allowed and added '{domain}' to network allowlist[/green bold]")
            else:
                self.console.print("[green bold]✓ Network access allowed once[/green bold]")
        else:
            self.console.print("[red bold]✗ Network access denied[/red bold]")
        self.console.print()

        return (approved, add_to_allowlist)
