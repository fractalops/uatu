"""Markdown rendering with custom styles for Uatu."""

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Heading as RichHeading
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text


class LeftAlignedHeading(RichHeading):
    """Heading that's left-aligned with enhanced styling."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"

        if self.tag == "h1":
            # H1: Bold with underline
            yield Text("")
            underline = Text("═" * len(text.plain), style="cyan")
            yield text
            yield underline
            yield Text("")
        elif self.tag == "h2":
            # H2: With prefix and spacing
            yield Text("")
            prefix = Text("▸ ", style="cyan bold")
            yield prefix + text
        elif self.tag == "h3":
            # H3: Subtle prefix
            prefix = Text("• ", style="cyan")
            yield prefix + text
        else:
            # H4+: Just the text
            yield text


class LeftAlignedMarkdown(RichMarkdown):
    """Markdown renderer with left-aligned headings."""

    elements = RichMarkdown.elements.copy()
    elements["heading_open"] = LeftAlignedHeading
