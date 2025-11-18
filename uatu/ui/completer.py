"""Autocompletion for slash commands."""

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class SlashCommandCompleter(Completer):
    """Autocomplete for slash commands in interactive chat."""

    def __init__(self):
        """Initialize with available slash commands."""
        self.commands = {
            "/help": "Show available commands and usage",
            "/exit": "Exit the chat session",
            "/quit": "Exit the chat session",
            "/clear": "Clear context (not supported - restart instead)",
            "/allowlist": "List all allowlisted commands",
            "/allowlist add": "Add command to allowlist (e.g., /allowlist add ps aux)",
            "/allowlist remove": "Remove pattern from allowlist (e.g., /allowlist remove ps)",
            "/allowlist clear": "Clear all allowlist entries",
        }

    def get_completions(self, document: Document, complete_event):
        """Generate completions for the current input.

        Args:
            document: Current document being edited
            complete_event: Completion event

        Yields:
            Completion objects for matching commands
        """
        text = document.text_before_cursor.lstrip()

        # Only complete if starts with /
        if not text.startswith("/"):
            return

        # Find matching commands
        for command, description in self.commands.items():
            if command.startswith(text):
                # Yield completion with the remaining text
                yield Completion(
                    text=command[len(text) :],
                    start_position=0,
                    display=command,
                    display_meta=description,
                )
