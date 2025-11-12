"""Token usage tracking for LLM calls."""

from dataclasses import dataclass, field

from rich.console import Console

console = Console()


@dataclass
class TokenUsage:
    """Track token usage across LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_calls: int = 0

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens used."""
        return self.input_tokens + self.output_tokens

    def add_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Add token usage from a single call."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_tokens += cache_creation_tokens
        self.cache_read_tokens += cache_read_tokens
        self.total_calls += 1

    def display_summary(self, budget: int | None = None) -> None:
        """
        Display token usage summary in Claude Code style.

        Args:
            budget: Optional token budget limit for context
        """
        if self.total_calls == 0:
            return

        # Calculate totals
        total = self.total_tokens
        remaining = budget - total if budget else None

        # Build usage string
        parts = []
        if self.cache_read_tokens > 0:
            parts.append(f"cache: {self.cache_read_tokens:,}")
        parts.append(f"in: {self.input_tokens:,}")
        parts.append(f"out: {self.output_tokens:,}")

        usage_str = " + ".join(parts)

        # Display in Claude Code style
        if budget and remaining is not None:
            console.print(f"[dim]Token usage: {usage_str} = {total:,}/{budget:,}; {remaining:,} remaining[/dim]")
        else:
            console.print(f"[dim]Token usage: {usage_str} = {total:,}[/dim]")

    def display_per_turn(self, turn: int, input_tokens: int, output_tokens: int, cache_read: int = 0) -> None:
        """
        Display token usage for a single turn in Claude Code style.

        Args:
            turn: The turn number
            input_tokens: Input tokens for this turn
            output_tokens: Output tokens for this turn
            cache_read: Cache read tokens for this turn
        """
        parts = []
        if cache_read > 0:
            parts.append(f"cache: {cache_read:,}")
        parts.append(f"in: {input_tokens:,}")
        parts.append(f"out: {output_tokens:,}")

        turn_total = input_tokens + output_tokens
        usage_str = " + ".join(parts)

        console.print(f"[dim]Turn {turn} tokens: {usage_str} = {turn_total:,}[/dim]")


@dataclass
class InvestigationStats:
    """Track statistics for an investigation session."""

    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Calculate investigation duration."""
        if self.end_time > 0:
            return self.end_time - self.start_time
        return 0.0

    def display_summary(self) -> None:
        """Display investigation summary."""
        if self.token_usage.total_calls > 0:
            self.token_usage.display_summary()

        if self.tool_calls > 0:
            console.print(f"[dim]Tool calls: {self.tool_calls}[/dim]")

        if self.duration_seconds > 0:
            console.print(f"[dim]Duration: {self.duration_seconds:.1f}s[/dim]")
