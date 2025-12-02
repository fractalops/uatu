"""Markdown rendering with custom styles for Uatu."""

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import (
    CodeBlock as RichCodeBlock,
)
from rich.markdown import Heading as RichHeading
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


class LeftAlignedHeading(RichHeading):
    """Heading that's left-aligned with enhanced styling."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = "left"

        if self.tag == "h1":
            # H1: Bold, no underline (cleaner)
            yield Text("")
            yield text
        elif self.tag == "h2":
            # H2: With prefix
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


class MinimalCodeBlock(RichCodeBlock):
    """Code block with minimal panel borders."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text)
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            word_wrap=False,
            background_color="default",
            padding=0,
        )
        # Wrap in minimal panel
        panel = Panel.fit(
            syntax,
            border_style="dim",
            padding=(0, 1),
        )
        yield panel


class LeftAlignedMarkdown(RichMarkdown):
    """Markdown renderer with left-aligned headings and minimal code blocks."""

    elements = RichMarkdown.elements.copy()
    elements["heading_open"] = LeftAlignedHeading
    elements["fence"] = MinimalCodeBlock
    elements["code_block"] = MinimalCodeBlock
