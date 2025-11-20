"""Tool definitions using Claude Agent SDK."""

import platform
from typing import Any

from claude_agent_sdk import tool

from uatu.capabilities import ToolCapabilities

# Initialize capabilities once
_capabilities = ToolCapabilities.detect()


@tool(
    name="list_processes",
    description="List all running processes with PID, name, CPU, memory, and command. "
    "Works by reading /proc on Linux or using ps on macOS.",
    input_schema={
        "type": "object",
        "properties": {
            "min_cpu_percent": {
                "type": "number",
                "description": "Only return processes above this CPU percentage (default: 5.0)",
                "default": 5.0,
            },
            "min_memory_mb": {
                "type": "number",
                "description": "Only return processes above this memory in MB (default: 100.0)",
                "default": 100.0,
            },
        },
        "required": [],
    },
)
async def list_processes(min_cpu_percent: float = 5.0, min_memory_mb: float = 100.0) -> dict[str, Any]:
    """List all running processes.

    Returns:
        MCP-formatted response with content blocks.
    """
    # Handle potential empty dict or None values from MCP client
    if isinstance(min_cpu_percent, dict) or min_cpu_percent is None:
        min_cpu_percent = 5.0
    if isinstance(min_memory_mb, dict) or min_memory_mb is None:
        min_memory_mb = 100.0

    # Import here to keep logic in existing files
    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import ListProcessesMac

        tool_impl = ListProcessesMac(_capabilities)
    else:
        from uatu.tools.proc_tools import ListProcesses

        tool_impl = ListProcesses(_capabilities)

    result = tool_impl.execute(min_cpu_percent=float(min_cpu_percent), min_memory_mb=float(min_memory_mb))

    # Return in MCP format
    import json

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    name="get_system_info",
    description="Get system-wide CPU, memory, and load information. Returns current resource usage statistics.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def get_system_info(*args, **kwargs) -> dict[str, Any]:
    """Get system resource information.

    Args:
        *args: Accepts positional arguments for MCP compatibility but ignores them.
        **kwargs: Accepts keyword arguments for MCP compatibility but ignores them.

    Returns:
        MCP-formatted response with content blocks.
    """
    # Ignore any arguments passed by MCP client (defensive programming)
    # MCP server may pass empty dict as positional arg
    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import GetSystemInfoMac

        tool_impl = GetSystemInfoMac(_capabilities)
    else:
        from uatu.tools.proc_tools import GetSystemInfo

        tool_impl = GetSystemInfo(_capabilities)

    result = tool_impl.execute()

    # Return in MCP format: {"content": [{"type": "text", "text": "..."}]}
    import json

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    name="get_process_tree",
    description="Get parent-child process relationships. Shows process tree structure "
    "to understand which processes spawned which others.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def get_process_tree(*args, **kwargs) -> dict[str, Any]:
    """Get process tree showing parent-child relationships.

    Args:
        *args: Accepts positional arguments for MCP compatibility but ignores them.
        **kwargs: Accepts keyword arguments for MCP compatibility but ignores them.

    Returns:
        MCP-formatted response with content blocks.
    """
    # Ignore any arguments passed by MCP client (defensive programming)
    # MCP server may pass empty dict as positional arg
    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import GetProcessTreeMac

        tool_impl = GetProcessTreeMac(_capabilities)
    else:
        from uatu.tools.proc_tools import GetProcessTree

        tool_impl = GetProcessTree(_capabilities)

    result = tool_impl.execute()

    # Return in MCP format
    import json

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    name="find_process_by_name",
    description="Find all processes matching a name pattern. Useful for locating "
    "specific applications or services by name.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Process name or pattern to search for (case-insensitive)",
            }
        },
        "required": ["name"],
    },
)
async def find_process_by_name(name: str) -> dict[str, Any]:
    """Find processes by name.

    Returns:
        MCP-formatted response with content blocks.
    """
    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import FindProcessByNameMac

        tool_impl = FindProcessByNameMac(_capabilities)
    else:
        from uatu.tools.command_tools import FindProcessByName

        tool_impl = FindProcessByName(_capabilities)

    result = tool_impl.execute(name=name)

    # Return in MCP format
    import json

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    name="check_port_binding",
    description="Check which process (if any) is listening on a specific port. "
    "Useful for diagnosing port conflicts. Uses ss/netstat or /proc/net/tcp.",
    input_schema={
        "type": "object",
        "properties": {
            "port": {
                "type": "integer",
                "description": "Port number to check (e.g., 8080, 443)",
            }
        },
        "required": ["port"],
    },
)
async def check_port_binding(port: int) -> dict[str, Any]:
    """Check what process is using a specific port.

    Returns:
        MCP-formatted response with content blocks.
    """
    from uatu.tools.command_tools import CheckPortBinding

    tool_impl = CheckPortBinding(_capabilities)
    result = tool_impl.execute(port=port)

    # Return in MCP format
    import json

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    name="read_proc_file",
    description="Read a file from /proc or /sys filesystem directly (Linux only). "
    "Low-level access to kernel data. Example: /proc/meminfo, /proc/123/status",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to file (must start with /proc or /sys)",
            }
        },
        "required": ["path"],
    },
)
async def read_proc_file(path: str) -> dict[str, Any]:
    """Read /proc or /sys file (Linux only).

    Returns:
        MCP-formatted response with content blocks.
    """
    if platform.system() == "Darwin":
        result = "Not available on macOS (no /proc filesystem)"
    else:
        from uatu.tools.proc_tools import ReadProcFile

        tool_impl = ReadProcFile(_capabilities)
        result = tool_impl.execute(path=path)

    # Return in MCP format
    return {"content": [{"type": "text", "text": str(result)}]}
