"""Approval prompt UI components."""

import asyncio
import threading
import time

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.widgets import Label
from rich.console import Console
from rich.live import Live
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

        options.append("\n(Use ↑↓ arrow keys, Enter to confirm)", style="dim")
        return options

    async def get_bash_approval(self, description: str, command: str) -> tuple[bool, bool]:
        """Get user approval for bash command with syntax highlighting.

        Args:
            description: Command description from agent
            command: The bash command to approve

        Returns:
            Tuple of (approved, add_to_allowlist)
        """
        self.console.print()
        self.console.print("[yellow]⚠ Bash command approval required[/yellow]")

        # Show description if provided
        if description:
            self.console.print(f"[dim]{description}[/dim]")

        # Detect risk category and get warning
        risk_style, risk_text, warning = AllowlistManager.detect_risk_category(command)

        # Show risk level
        self.console.print(f"[dim]Risk: [{risk_style}]{risk_text}[/{risk_style}][/dim]")

        # Show warning if this is a dangerous operation
        if warning:
            self.console.print()
            self.console.print(f"[{risk_style}]⚠ Warning:[/{risk_style}] {warning}")
            self.console.print()

        # Show syntax-highlighted command
        self.console.print()
        command_display = Syntax(command, "bash", theme="monokai", background_color="default")
        self.console.print(command_display)
        self.console.print()

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
            result = await loop.run_in_executor(None, run_app)

            # Stop the update thread
            running[0] = False
            update_thread.join(timeout=0.5)

        # 0 = Allow, 1 = Always allow, 2 = Deny
        approved = result in [0, 1]
        add_to_allowlist = result == 1

        # Show clear confirmation with status indicator
        self.console.print()
        if approved:
            if add_to_allowlist:
                base_cmd = AllowlistManager.get_base_command(command)
                if base_cmd in AllowlistManager.SAFE_BASE_COMMANDS:
                    self.console.print(f"[green]✓ Allowed and added '{base_cmd}' to allowlist[/green]")
                else:
                    self.console.print("[green]✓ Allowed and added exact command to allowlist[/green]")
            else:
                self.console.print("[green]✓ Allowed once[/green]")
        else:
            self.console.print("[red]✗ Denied[/red]")
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

        options.append("\n(Use ↑↓ arrow keys, Enter to confirm)", style="dim")
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

        self.console.print()
        self.console.print("[yellow]⚠ Network access requested[/yellow]")
        self.console.print(f"[dim]Tool:   {tool_name}[/dim]")
        self.console.print(f"[dim]Domain: [yellow bold]{domain}[/yellow bold][/dim]")
        self.console.print(f"[dim]URL:    {url}[/dim]")
        self.console.print()
        self.console.print("[yellow]This will fetch content from the internet[/yellow]")
        self.console.print()

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
            result = await loop.run_in_executor(None, run_app)

            running[0] = False
            update_thread.join(timeout=0.5)

        # 0 = Allow, 1 = Always allow, 2 = Deny
        approved = result in [0, 1]
        add_to_allowlist = result == 1

        # Show confirmation with status indicator
        self.console.print()
        if approved:
            if add_to_allowlist:
                self.console.print(f"[green]✓ Allowed and added '{domain}' to network allowlist[/green]")
            else:
                self.console.print("[green]✓ Network access allowed once[/green]")
        else:
            self.console.print("[red]✗ Network access denied[/red]")
        self.console.print()

        return (approved, add_to_allowlist)
