"""Tool result preview formatter.

Provides minimalistic previews of tool execution results to give users
visibility into what data was retrieved without overwhelming the UI.
"""

from typing import Any


class ToolPreviewFormatter:
    """Formats tool results into minimal previews."""

    MAX_PREVIEW_LENGTH = 90  # Keep inline summaries short
    MAX_LINES_TO_SHOW = 3  # Inline summaries only show a few lines

    @classmethod
    def format_preview(cls, tool_name: str, tool_response: Any) -> str | None:
        """Format a tool response into a minimal preview string.

        Args:
            tool_name: Name of the tool that was executed
            tool_response: The tool's response data

        Returns:
            Formatted preview string, or None if no preview needed
        """
        # Unwrap MCP content format: [{'type': 'text', 'text': '...'}]
        unwrapped_response = cls._unwrap_mcp_content(tool_response)

        # Handle Bash tool results
        if tool_name == "Bash" or "bash" in tool_name.lower():
            return cls._format_bash_preview(unwrapped_response)

        # Handle MCP tool results
        if tool_name.startswith("mcp__"):
            return cls._format_mcp_preview(tool_name, unwrapped_response)

        # Handle network tools
        if tool_name in ("WebFetch", "WebSearch"):
            return cls._format_network_preview(tool_name, unwrapped_response)

        # Default: show type and size
        return cls._format_default_preview(unwrapped_response)

    @classmethod
    def _unwrap_mcp_content(cls, response: Any) -> Any:
        """Unwrap MCP content format if present.

        MCP responses come as: [{'type': 'text', 'text': 'actual data'}]
        This extracts the actual data.
        """
        if isinstance(response, list) and len(response) > 0:
            first_item = response[0]
            if isinstance(first_item, dict) and "type" in first_item and "text" in first_item:
                # This is MCP content format - extract the text
                text = first_item["text"]
                # Try to parse as JSON if it looks like JSON
                if text.strip().startswith(("{", "[")):
                    try:
                        import json
                        return json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        return text
                return text
        return response

    @classmethod
    def _format_bash_preview(cls, response: Any) -> str:
        """Format Bash command output preview.

        Shows line count and first line of output (inline).
        """
        if not response:
            return "✓ No output"

        output = ""

        # Response can be a string, dict, or have various structures
        if isinstance(response, str):
            output = response
        elif isinstance(response, dict):
            # Try different possible keys
            output = (
                response.get("stdout", "")
                or response.get("output", "")
                or response.get("result", "")
                or response.get("stderr", "")
                or str(response.get("content", ""))
            )
        elif hasattr(response, "content"):
            # SDK might wrap response
            output = str(response.content)
        else:
            # Fallback: stringify whatever we got
            output = str(response) if response else ""

        # Normalize to string for safe checks
        if not isinstance(output, str):
            output = str(output)

        if not output or not output.strip():
            return "✓ No output"

        # Filter out SDK-internal permission messages - these are noisy and already handled by our permission handler
        lowered = output.lower()
        if "hook requested permission" in lowered or "permission behavior:" in lowered:
            return None  # Don't show anything - our permission handler already printed the user-friendly message

        lines = output.strip().split("\n")
        line_count = len(lines)

        first_line = lines[0].strip()
        if len(first_line) > cls.MAX_PREVIEW_LENGTH:
            first_line = first_line[: cls.MAX_PREVIEW_LENGTH - 3] + "..."

        if line_count == 1:
            return f"✓ {first_line}"
        return f"✓ {line_count} lines | {first_line}"

    @classmethod
    def _format_mcp_preview(cls, tool_name: str, response: Any) -> str:
        """Format MCP tool result preview as a single line."""
        # Extract the actual tool name (remove mcp__ prefix and server name)
        parts = tool_name.split("__")
        clean_name = parts[-1].replace("_", " ").title() if len(parts) > 1 else tool_name

        def _num(val: Any, default: float = 0.0) -> float:
            try:
                if isinstance(val, int | float):
                    return float(val)
                return float(str(val))
            except Exception:
                return default
        try:
            # Handle different response types
            if isinstance(response, dict):
                # Special handling for get_system_info
                if "memory" in response and "load" in response:
                    mem = response.get("memory", {}) or {}
                    load = response.get("load", {}) or {}
                    mem_pct = _num(mem.get("percent"), 0.0)
                    load_1m = _num(load.get("1min"), 0.0)
                    return f"✓ mem {mem_pct:.0f}% | load {load_1m:.1f}"

                # Special handling for process tree
                if "total_processes" in response:
                    total = response["total_processes"]
                    return f"✓ {total} processes"

                # Try to extract meaningful summary
                if "count" in response:
                    return f"✓ {response['count']} items"
                if len(response) == 0:
                    return "✓ Empty result"
                key_count = len(response.keys())
                return f"✓ {key_count} fields"

            if isinstance(response, list):
                count = len(response)
                # Check if it's a list of processes
                if count > 0 and isinstance(response[0], dict) and "pid" in response[0]:
                    return f"✓ {count} processes"
                item_type = clean_name.rstrip("s")  # Remove plural 's' if present
                plural = "s" if count != 1 else ""
                return f"✓ {count} {item_type.lower()}{plural}"

            if isinstance(response, str):
                # Short string responses
                if len(response) <= cls.MAX_PREVIEW_LENGTH:
                    return f"✓ {response}"
                return f"✓ {response[: cls.MAX_PREVIEW_LENGTH - 3]}..."

            return f"✓ {type(response).__name__}"
        except Exception as e:  # pragma: no cover - defensive
            return f"✓ error: {e}"

    @classmethod
    def _format_network_preview(cls, tool_name: str, response: Any) -> str:
        """Format network tool result preview."""
        if isinstance(response, dict):
            # WebFetch might have status_code and content
            status = response.get("status_code", "")
            content = response.get("content", "") or response.get("result", "")

            if status:
                # Calculate size
                size = len(str(content)) if content else 0
                size_str = cls._format_bytes(size)
                return f"✓ {status} ({size_str})"

        # WebSearch results
        if isinstance(response, list):
            return f"✓ {len(response)} results"

        return "✓ Response received"

    @classmethod
    def _format_default_preview(cls, response: Any) -> str:
        """Format generic response preview."""
        if isinstance(response, list | tuple):
            return f"✓ {len(response)} items"

        elif isinstance(response, dict):
            if not response:
                return "✓ Empty result"
            return f"✓ {len(response)} fields"

        elif isinstance(response, str):
            if not response:
                return "✓ Empty string"
            lines = response.split("\n")
            if len(lines) > 1:
                return f"✓ {len(lines)} lines"
            elif len(response) <= cls.MAX_PREVIEW_LENGTH:
                return f"✓ {response}"
            else:
                return f"✓ {response[:cls.MAX_PREVIEW_LENGTH - 3]}..."

        elif isinstance(response, int | float):
            return f"✓ {response}"

        elif response is None:
            return "✓ No result"

        return f"✓ {type(response).__name__}"

    @classmethod
    def _format_bytes(cls, size: int) -> str:
        """Format byte size in human-readable format."""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"
