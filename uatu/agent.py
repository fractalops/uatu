"""Core agent orchestration using Claude Agent SDK."""

import time
from collections.abc import Callable

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, query

from uatu.config import get_settings
from uatu.token_tracker import InvestigationStats
from uatu.tools import create_system_tools_mcp_server


class UatuAgent:
    """The Watcher - An agentic system troubleshooting assistant."""

    def __init__(self) -> None:
        """Initialize the Uatu agent."""
        self.settings = get_settings()

        # System prompt for the agent
        self.system_prompt = """You are Uatu, The Watcher - an expert system troubleshooting agent.

Your role is to:
1. Observe system state using available tools
2. Identify patterns and anomalies
3. Diagnose root causes
4. Provide actionable recommendations with risk assessment

When analyzing issues:
- Look for common patterns: crash loops, port conflicts, zombie processes, resource exhaustion
- Consider parent-child process relationships
- Correlate multiple signals (CPU, memory, process counts)
- Explain your reasoning clearly
- Cite specific evidence (PIDs, process names, resource usage)

Be concise but thorough. Focus on actionable insights."""

    async def investigate(
        self, symptom: str, on_event: Callable[[str, dict], None] | None = None
    ) -> tuple[str, InvestigationStats]:
        """
        Investigate a system issue based on symptoms.

        Args:
            symptom: Description of the problem or symptom
            on_event: Optional callback for streaming events (type, data)

        Returns:
            Tuple of (analysis text, investigation stats)
        """
        # Track investigation stats
        stats = InvestigationStats()
        stats.start_time = time.time()

        # Note: API key is read from ANTHROPIC_API_KEY environment variable by SDK
        # Create agent options with MCP server
        options = ClaudeAgentOptions(
            model=self.settings.uatu_model,
            system_prompt=self.system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
            max_turns=10,
        )

        # Use SDK's query function
        response_text = ""

        try:
            async for message in query(
                prompt=f"Please investigate this system issue: {symptom}", options=options
            ):
                # Track token usage from ResultMessage (contains final usage stats)
                if isinstance(message, ResultMessage):
                    if hasattr(message, "usage") and message.usage is not None:
                        usage = message.usage
                        stats.token_usage.add_usage(
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                        )

                # Stream assistant messages (thinking/reasoning)
                if isinstance(message, AssistantMessage) and hasattr(message, "content"):
                    for block in message.content:
                        # Text blocks - reasoning/thinking
                        if hasattr(block, "text"):
                            text = block.text
                            response_text += text
                            if on_event:
                                on_event("text", {"content": text})

                        # Tool use blocks - show what tools are being called
                        elif hasattr(block, "name"):
                            stats.tool_calls += 1
                            tool_name = block.name
                            tool_input = getattr(block, "input", {})
                            if on_event:
                                on_event("tool_use", {"name": tool_name, "input": tool_input})

                # Tool results - show what tools returned
                elif hasattr(message, "content"):
                    for block in message.content:
                        if hasattr(block, "content") and hasattr(block, "tool_use_id"):
                            if on_event:
                                on_event(
                                    "tool_result",
                                    {
                                        "tool_use_id": block.tool_use_id,
                                        "content": block.content,
                                        "is_error": getattr(block, "is_error", False),
                                    },
                                )
        except Exception as e:
            # If there's an error, return what we have so far with error message
            response_text += f"\n\n[Investigation interrupted: {str(e)}]"
            if on_event:
                on_event("error", {"message": str(e)})

        stats.end_time = time.time()

        return response_text, stats
