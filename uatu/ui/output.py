"""Output interface protocol for Uatu.

This module defines the output abstraction layer, allowing different
implementations (console, file, testing, etc.) without tight coupling.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class OutputWriter(Protocol):
    """Protocol for output operations.

    This protocol defines the minimum interface required for output in Uatu.
    Implementations can be Rich Console, file writers, testing mocks, etc.
    """

    def print(self, *args, **kwargs) -> None:
        """Print output.

        Args:
            *args: Content to print
            **kwargs: Additional formatting options (implementation-specific)
        """
        ...

    def print_error(self, message: str) -> None:
        """Print error message.

        Args:
            message: Error message to display
        """
        ...

    def print_status(self, message: str, status: str = "info") -> None:
        """Print status message with indicator.

        Args:
            message: Status message
            status: Status type (success, error, warning, info)
        """
        ...

    def print_panel(self, content: str, title: str = "", border_style: str = "cyan") -> None:
        """Print content in a panel/box.

        Args:
            content: Panel content
            title: Optional panel title
            border_style: Border color/style
        """
        ...


class ConsoleOutputWriter:
    """Rich Console implementation of OutputWriter.

    Wraps Rich Console to conform to the OutputWriter protocol.
    """

    def __init__(self, console):
        """Initialize with Rich Console.

        Args:
            console: Rich Console instance
        """
        from rich.console import Console
        from rich.panel import Panel

        self.console = console if console else Console()
        self._Panel = Panel

    def print(self, *args, **kwargs) -> None:
        """Print using Rich Console."""
        self.console.print(*args, **kwargs)

    def print_error(self, message: str) -> None:
        """Print error in red."""
        self.console.print(f"[red]Error: {message}[/red]")

    def print_status(self, message: str, status: str = "info") -> None:
        """Print status with colored indicator."""
        icons = {
            "success": ("✓", "green"),
            "error": ("✗", "red"),
            "warning": ("!", "yellow"),
            "info": ("→", "cyan"),
        }
        icon, color = icons.get(status, ("→", "cyan"))
        self.console.print(f"[{color}]{icon}[/{color}] {message}")

    def print_panel(self, content: str, title: str = "", border_style: str = "cyan") -> None:
        """Print content in a Rich Panel."""
        self.console.print(self._Panel(content, title=title, border_style=border_style))


class TestOutputWriter:
    """Test implementation of OutputWriter that captures output.

    Useful for testing without actual console output.
    """

    def __init__(self):
        """Initialize test output writer."""
        self.messages: list[tuple[str, str]] = []  # (type, content)

    def print(self, *args, **kwargs) -> None:
        """Capture print output."""
        content = " ".join(str(arg) for arg in args)
        self.messages.append(("print", content))

    def print_error(self, message: str) -> None:
        """Capture error output."""
        self.messages.append(("error", message))

    def print_status(self, message: str, status: str = "info") -> None:
        """Capture status output."""
        self.messages.append(("status", f"{status}: {message}"))

    def print_panel(self, content: str, title: str = "", border_style: str = "cyan") -> None:
        """Capture panel output."""
        self.messages.append(("panel", f"{title}: {content}" if title else content))

    def clear(self) -> None:
        """Clear captured messages."""
        self.messages.clear()

    def get_messages(self, message_type: str | None = None) -> list[str]:
        """Get captured messages, optionally filtered by type.

        Args:
            message_type: Optional filter by message type

        Returns:
            List of message contents
        """
        if message_type:
            return [content for mtype, content in self.messages if mtype == message_type]
        return [content for _, content in self.messages]
