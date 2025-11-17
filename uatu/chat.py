"""Interactive chat interface for Uatu.

This module provides a thin wrapper around the chat session components.
The actual implementation is in uatu.chat_session.session.
"""

from uatu.chat_session.session import ChatSession
from uatu.ui.markdown import LeftAlignedMarkdown

# Export for backwards compatibility
__all__ = ["UatuChat", "LeftAlignedMarkdown"]


class UatuChat:
    """Interactive chat interface for Uatu.

    This is a thin wrapper around ChatSession for backwards compatibility.
    """

    def __init__(self) -> None:
        """Initialize chat interface."""
        self.session = ChatSession()

    def run(self) -> None:
        """Run the interactive chat loop."""
        self.session.run()
