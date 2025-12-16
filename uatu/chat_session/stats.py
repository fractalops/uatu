"""Session statistics tracking and display."""

from dataclasses import dataclass


@dataclass
class SessionStats:
    """Tracks statistics for a chat session."""

    conversation_turns: int = 0  # User-facing conversation turns
    internal_turns: int = 0  # SDK internal turns (includes tool calls)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    last_turn_input_tokens: int = 0
    last_turn_output_tokens: int = 0
    last_turn_cost_usd: float = 0.0
    max_budget_usd: float | None = None
    last_turn_tool_count: int = 0
    last_turn_status: str = "ok"
    last_turn_elapsed_ms: float | None = None
    last_turn_bg_soft_denies: int = 0
    last_turn_bg_hard_denies: int = 0
    # Enhanced ResultMessage tracking
    sdk_session_id: str | None = None
    total_api_duration_ms: int = 0
    last_turn_api_duration_ms: int = 0
    total_duration_ms: int = 0
    last_turn_duration_ms: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def update_from_result(self, result_message) -> None:
        """Update stats from a ResultMessage.

        Args:
            result_message: ResultMessage from Claude SDK

        ResultMessage fields (from sdk.md):
            - duration_ms: Total duration in milliseconds
            - duration_api_ms: API-only duration in milliseconds
            - is_error: Whether the result is an error
            - num_turns: Number of internal turns
            - session_id: SDK session identifier
            - total_cost_usd: Total cost in USD
            - usage: Token usage breakdown
            - result: Final result text (if any)
        """
        # Increment conversation turn (each user message)
        self.conversation_turns += 1

        # Update internal turn count from SDK
        self.internal_turns = result_message.num_turns

        # Track SDK session ID
        if hasattr(result_message, "session_id") and result_message.session_id:
            self.sdk_session_id = result_message.session_id

        # Update cost
        if result_message.total_cost_usd is not None:
            # Track delta for last turn
            new_cost = result_message.total_cost_usd
            self.last_turn_cost_usd = new_cost - self.total_cost_usd
            self.total_cost_usd = new_cost

        # Update duration tracking
        if hasattr(result_message, "duration_ms") and result_message.duration_ms:
            self.last_turn_duration_ms = result_message.duration_ms
            self.total_duration_ms += result_message.duration_ms

        if hasattr(result_message, "duration_api_ms") and result_message.duration_api_ms:
            self.last_turn_api_duration_ms = result_message.duration_api_ms
            self.total_api_duration_ms += result_message.duration_api_ms

        # Update token counts from usage dict
        if result_message.usage:
            # Claude SDK usage format: {'input_tokens': X, 'output_tokens': Y}
            input_tokens = result_message.usage.get("input_tokens", 0)
            output_tokens = result_message.usage.get("output_tokens", 0)

            # Track delta for last turn
            self.last_turn_input_tokens = input_tokens - self.total_input_tokens
            self.last_turn_output_tokens = output_tokens - self.total_output_tokens

            self.total_input_tokens = input_tokens
            self.total_output_tokens = output_tokens

            # Track cache tokens if available
            if "cache_read_input_tokens" in result_message.usage:
                self.cache_read_tokens = result_message.usage.get("cache_read_input_tokens", 0)
            if "cache_creation_input_tokens" in result_message.usage:
                self.cache_write_tokens = result_message.usage.get("cache_creation_input_tokens", 0)

    def format_compact(self) -> str:
        """Format stats as compact one-line display.

        Returns:
            Formatted stats string for corner display
        """
        total_tokens = self.total_input_tokens + self.total_output_tokens
        last_turn_tokens = self.last_turn_input_tokens + self.last_turn_output_tokens

        # Format tokens with K suffix
        def format_tokens(count: int) -> str:
            if count >= 1000:
                return f"{count / 1000:.1f}K"
            return str(count)

        # Format cost
        cost_str = f"${self.total_cost_usd:.4f}" if self.total_cost_usd > 0 else "$0.00"
        budget_str = ""
        if self.max_budget_usd is not None and self.total_cost_usd is not None:
            remaining = max(self.max_budget_usd - self.total_cost_usd, 0)
            budget_str = f" | budget ${remaining:.4f} left"

        meta = []
        if self.last_turn_tool_count:
            meta.append(f"tools:{self.last_turn_tool_count}")
        if self.last_turn_elapsed_ms is not None:
            meta.append(f"{self.last_turn_elapsed_ms/1000:.0f}s")
        if self.last_turn_bg_soft_denies or self.last_turn_bg_hard_denies:
            meta.append(f"bg-blocks:{self.last_turn_bg_soft_denies}/{self.last_turn_bg_hard_denies}")

        parts = [
            f"Conv {self.conversation_turns} ({self.internal_turns} internal)",
            f"{format_tokens(last_turn_tokens)} tok",
            f"Session: {format_tokens(total_tokens)}",
            cost_str,
        ]
        if meta:
            parts.append(" ".join(meta))

        return " | ".join(parts) + budget_str

    def update_turn_meta(
        self,
        tool_count: int,
        status: str,
        elapsed_ms: float | None,
        bg_soft_denies: int = 0,
        bg_hard_denies: int = 0,
    ) -> None:
        """Track last turn metadata for display."""
        self.last_turn_tool_count = tool_count
        self.last_turn_status = status
        self.last_turn_elapsed_ms = elapsed_ms
        self.last_turn_bg_soft_denies = bg_soft_denies
        self.last_turn_bg_hard_denies = bg_hard_denies

    def reset(self) -> None:
        """Reset all statistics to initial state."""
        self.conversation_turns = 0
        self.internal_turns = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.last_turn_input_tokens = 0
        self.last_turn_output_tokens = 0
        self.last_turn_cost_usd = 0.0
        self.last_turn_tool_count = 0
        self.last_turn_status = "ok"
        self.last_turn_elapsed_ms = None
        self.last_turn_bg_soft_denies = 0
        self.last_turn_bg_hard_denies = 0
        # Reset enhanced tracking
        self.sdk_session_id = None
        self.total_api_duration_ms = 0
        self.last_turn_api_duration_ms = 0
        self.total_duration_ms = 0
        self.last_turn_duration_ms = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
