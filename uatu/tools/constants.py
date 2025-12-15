"""Tool name constants for Uatu.

This module centralizes all tool names to avoid magic strings throughout the codebase.
"""

from typing import Final


class Tools:
    """Tool name constants."""

    # MCP System Tools
    GET_SYSTEM_INFO: Final[str] = "mcp__system-tools__get_system_info"
    LIST_PROCESSES: Final[str] = "mcp__system-tools__list_processes"
    GET_PROCESS_TREE: Final[str] = "mcp__system-tools__get_process_tree"
    FIND_PROCESS_BY_NAME: Final[str] = "mcp__system-tools__find_process_by_name"
    CHECK_PORT_BINDING: Final[str] = "mcp__system-tools__check_port_binding"
    READ_PROC_FILE: Final[str] = "mcp__system-tools__read_proc_file"
    GET_DIRECTORY_SIZES: Final[str] = "mcp__system-tools__get_directory_sizes"
    FIND_LARGE_FILES: Final[str] = "mcp__system-tools__find_large_files"
    DISK_SCAN_SUMMARY: Final[str] = "mcp__system-tools__disk_scan_summary"
    GET_CONNECTION_SUMMARY: Final[str] = "mcp__system-tools__get_connection_summary"
    GET_RESOURCE_HOGS: Final[str] = "mcp__system-tools__get_resource_hogs"
    GET_PROCESS_THREADS: Final[str] = "mcp__system-tools__get_process_threads"
    GET_PROCESS_FILES: Final[str] = "mcp__system-tools__get_process_files"

    # SDK Built-in Tools
    BASH: Final[str] = "Bash"
    BASH_OUTPUT: Final[str] = "BashOutput"
    KILL_SHELL: Final[str] = "KillShell"
    WEB_FETCH: Final[str] = "WebFetch"
    WEB_SEARCH: Final[str] = "WebSearch"

    # Tool Groups
    MCP_TOOLS: Final[frozenset[str]] = frozenset([
        GET_SYSTEM_INFO,
        LIST_PROCESSES,
        GET_PROCESS_TREE,
        FIND_PROCESS_BY_NAME,
        CHECK_PORT_BINDING,
        READ_PROC_FILE,
        GET_DIRECTORY_SIZES,
        FIND_LARGE_FILES,
        DISK_SCAN_SUMMARY,
        GET_CONNECTION_SUMMARY,
        GET_RESOURCE_HOGS,
        GET_PROCESS_THREADS,
        GET_PROCESS_FILES,
    ])
    MCP_SAFE_TOOLS: Final[frozenset[str]] = MCP_TOOLS
    SAFE_HINT_TOOLS: Final[frozenset[str]] = frozenset([
        "safe-hints__top_processes",
        "safe-hints__disk_usage_summary",
        "safe-hints__listening_ports_hint",
    ])

    NETWORK_TOOLS: Final[frozenset[str]] = frozenset([
        WEB_FETCH,
        WEB_SEARCH,
    ])

    BASH_TOOLS: Final[frozenset[str]] = frozenset([
        BASH,
        "mcp__bash",  # Potential variant
    ])

    READ_ONLY_TOOLS: Final[frozenset[str]] = frozenset([
        BASH_OUTPUT,  # Read output from background bash shells
        KILL_SHELL,   # Kill a background shell (doesn't execute new commands)
    ])

    ALL_ALLOWED_TOOLS: Final[list[str]] = [
        GET_SYSTEM_INFO,
        LIST_PROCESSES,
        GET_PROCESS_TREE,
        FIND_PROCESS_BY_NAME,
        CHECK_PORT_BINDING,
        READ_PROC_FILE,
        GET_DIRECTORY_SIZES,
        FIND_LARGE_FILES,
        DISK_SCAN_SUMMARY,
        GET_CONNECTION_SUMMARY,
        GET_RESOURCE_HOGS,
        GET_PROCESS_THREADS,
        GET_PROCESS_FILES,
        # Safe hints (lightweight, read-only helpers)
        *SAFE_HINT_TOOLS,
        BASH,
        WEB_FETCH,
        WEB_SEARCH,
    ]

    @classmethod
    def is_mcp_tool(cls, tool_name: str) -> bool:
        """Check if a tool is an MCP tool.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool is an MCP tool
        """
        return tool_name in cls.MCP_TOOLS

    @classmethod
    def is_network_tool(cls, tool_name: str) -> bool:
        """Check if a tool is a network tool.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool is a network tool
        """
        return tool_name in cls.NETWORK_TOOLS

    @classmethod
    def is_bash_tool(cls, tool_name: str) -> bool:
        """Check if a tool is a bash tool that requires approval.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool is a bash tool that requires approval

        Note:
            BashOutput and KillShell are NOT considered bash tools for approval
            purposes since they don't execute new commands.
        """
        # Explicitly exclude read-only tools
        if tool_name in cls.READ_ONLY_TOOLS:
            return False
        return tool_name in cls.BASH_TOOLS or "bash" in tool_name.lower()
