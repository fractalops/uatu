"""MCP server with safe, scoped system probes to reduce Bash reliance."""

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool


@tool("top_processes", "List top processes by CPU/mem (safe, limited)", {"limit": int})
async def top_processes(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit", 5)), 20))
    return {
        "content": [
            {
                "type": "text",
                "text": f"Use 'ps aux | sort -k3 -rn | head -n {limit}'",
            }
        ]
    }


@tool("disk_usage_summary", "Summarize disk usage per mount", {})
async def disk_usage_summary(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": "Use 'df -h' to list filesystems with usage%"},
        ]
    }


@tool("listening_ports_hint", "Show listening ports (non-invasive)", {})
async def listening_ports_hint(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": "Use 'lsof -i -P -n | grep LISTEN' or 'ss -tlnp' for listening ports",
            },
        ]
    }


def create_safe_mcp_server() -> Any:
    """Create an SDK MCP server exposing safe hints to steer the agent."""
    return create_sdk_mcp_server(
        name="safe-hints",
        version="1.0.0",
        tools=[top_processes, disk_usage_summary, listening_ports_hint],
    )

