"""LLM-powered investigation of anomalies."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query

from uatu.config import get_settings
from uatu.tools import create_system_tools_mcp_server
from uatu.watcher.models import AnomalyEvent, SystemSnapshot


class InvestigationCache:
    """Cache investigations to avoid repeated LLM calls for same issue."""

    def __init__(self, cache_file: Path | None = None):
        """Initialize cache."""
        self.cache_file = cache_file or Path.home() / ".uatu" / "investigation_cache.json"
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """Load cache from disk."""
        if not self.cache_file.exists():
            return {}

        try:
            with open(self.cache_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass

    def get_cache_key(self, event: AnomalyEvent) -> str:
        """Generate cache key for an event."""
        # Hash based on type + key details
        key_data = f"{event.type.value}:{event.message}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]

    def get(self, event: AnomalyEvent) -> dict[str, Any] | None:
        """Get cached investigation if available and recent."""
        key = self.get_cache_key(event)

        if key not in self.cache:
            return None

        cached = self.cache[key]

        # Check if cache is too old (1 hour)
        cached_time = datetime.fromisoformat(cached["timestamp"])
        if datetime.now() - cached_time > timedelta(hours=1):
            return None

        return cached

    def set(self, event: AnomalyEvent, investigation: str) -> None:
        """Cache an investigation."""
        key = self.get_cache_key(event)

        self.cache[key] = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event.type.value,
            "event_message": event.message,
            "investigation": investigation,
            "count": self.cache.get(key, {}).get("count", 0) + 1,
        }

        self._save_cache()


class Investigator:
    """Investigates anomalies using Claude."""

    def __init__(self):
        """Initialize investigator."""
        self.settings = get_settings()
        self.cache = InvestigationCache()

        # System prompt for investigations
        self.system_prompt = """You are Uatu, The Watcher - investigating a system anomaly.

Your task:
1. Understand what anomaly was detected
2. Use available tools to gather relevant context
3. Determine the likely root cause
4. Provide actionable recommendations

Be concise but thorough. Focus on:
- Why this happened
- What's the impact
- How to fix it
- How to prevent it

Format your response in markdown with clear sections."""

    async def investigate(self, event: AnomalyEvent, snapshot: SystemSnapshot) -> dict[str, str]:
        """
        Investigate an anomaly event.

        Args:
            event: The anomaly event to investigate
            snapshot: Current system snapshot

        Returns:
            Dictionary with 'analysis' and 'cached' keys
        """
        # Check cache first
        cached = self.cache.get(event)
        if cached:
            return {
                "analysis": cached["investigation"],
                "cached": True,
                "cache_count": cached["count"],
            }

        # Prepare investigation prompt
        investigation_prompt = f"""I detected this system anomaly:

**Event**: {event.message}
**Type**: {event.type.value}
**Severity**: {event.severity.string_value}
**Time**: {event.timestamp.strftime("%Y-%m-%d %H:%M:%S")}

**Details**:
{json.dumps(event.details, indent=2)}

**System State**:
- CPU: {snapshot.cpu_percent:.1f}%
- Memory: {snapshot.memory_percent:.1f}% ({snapshot.memory_used_mb:.0f}MB / {snapshot.memory_total_mb:.0f}MB)
- Load: {snapshot.load_1min:.2f}
- Processes: {snapshot.process_count}

Please investigate this anomaly. Use tools if needed to gather more context."""

        # Create agent options with MCP server
        # Watch mode uses read-only tools only for safety
        allowed_tools = [
            "mcp__system-tools__get_system_info",
            "mcp__system-tools__list_processes",
            "mcp__system-tools__get_process_tree",
            "mcp__system-tools__find_process_by_name",
            "mcp__system-tools__check_port_binding",
            "mcp__system-tools__read_proc_file",
        ]

        # Use bypassPermissions for watch mode since all tools are read-only
        # Safety is enforced by limiting allowed_tools to read-only operations
        options = ClaudeAgentOptions(
            api_key=self.settings.anthropic_api_key,
            model=self.settings.uatu_model,
            max_tokens=self.settings.uatu_max_tokens,
            temperature=self.settings.uatu_temperature,
            system_prompt=self.system_prompt,
            mcp_servers={"system-tools": create_system_tools_mcp_server()},
            max_turns=5,  # Limit investigation depth
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
        )

        # Use SDK's query function
        analysis_text = ""
        async for message in query(investigation_prompt, options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        analysis_text += block.text

        # Cache the investigation
        self.cache.set(event, analysis_text)

        return {
            "analysis": analysis_text,
            "cached": False,
            "cache_count": 1,
        }
