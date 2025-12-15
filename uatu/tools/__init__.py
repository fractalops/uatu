"""System analysis tools for the Uatu agent."""

import platform
from typing import Any

from uatu.capabilities import ToolCapabilities
from uatu.tools.base import ToolRegistry
from uatu.tools.command_tools import CheckPortBinding, FindProcessByName
from uatu.tools.proc_tools import (
    GetProcessTree,
    GetSystemInfo,
    ListProcesses,
    ReadProcFile,
)
from uatu.tools.processes import ProcessAnalyzer
from uatu.tools.safe_mcp import create_safe_mcp_server


def create_system_tools_mcp_server(capabilities: ToolCapabilities | None = None) -> Any:
    """
    Create MCP server with system troubleshooting tools using Claude Agent SDK.

    Args:
        capabilities: Optional pre-detected capabilities. If None, will auto-detect.

    Returns:
        MCP server instance
    """
    from claude_agent_sdk import create_sdk_mcp_server

    from uatu.tools.sdk_tools import (
        check_port_binding,
        disk_scan_summary,
        find_large_files,
        find_process_by_name,
        get_connection_summary,
        # Additional diagnostics
        get_directory_sizes,
        get_process_files,
        get_process_threads,
        get_process_tree,
        get_resource_hogs,
        get_system_info,
        list_processes,
        read_proc_file,
    )

    return create_sdk_mcp_server(
        name="system-tools",
        tools=[
            list_processes,
            get_system_info,
            get_process_tree,
            find_process_by_name,
            check_port_binding,
            read_proc_file,
            # Additional diagnostics
            get_directory_sizes,
            find_large_files,
            disk_scan_summary,
            get_connection_summary,
            get_resource_hogs,
            get_process_threads,
            get_process_files,
        ],
    )


def create_tool_registry(capabilities: ToolCapabilities | None = None) -> ToolRegistry:
    """
    Create and populate the tool registry.

    Args:
        capabilities: Optional pre-detected capabilities. If None, will auto-detect.

    Returns:
        Configured ToolRegistry
    """
    if capabilities is None:
        capabilities = ToolCapabilities.detect()

    registry = ToolRegistry(capabilities)

    is_macos = platform.system() == "Darwin"

    if is_macos:
        # macOS: Use BSD-style tools
        from uatu.tools.macos_tools import (
            FindProcessByNameMac,
            GetProcessTreeMac,
            GetSystemInfoMac,
            ListProcessesMac,
        )

        registry.register(ListProcessesMac)
        registry.register(GetSystemInfoMac)
        registry.register(GetProcessTreeMac)
        registry.register(FindProcessByNameMac)

    else:
        # Linux: Use /proc-based tools
        registry.register(ReadProcFile)
        registry.register(ListProcesses)
        registry.register(GetSystemInfo)
        registry.register(GetProcessTree)
        registry.register(FindProcessByName)

    # Cross-platform tools
    registry.register(CheckPortBinding)

    return registry


__all__ = [
    "ProcessAnalyzer",
    "ToolCapabilities",
    "ToolRegistry",
    "create_tool_registry",
    "create_system_tools_mcp_server",
    "create_safe_mcp_server",
]
