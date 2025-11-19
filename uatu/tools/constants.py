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

    # SDK Built-in Tools
    BASH: Final[str] = "Bash"
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
    ])

    NETWORK_TOOLS: Final[frozenset[str]] = frozenset([
        WEB_FETCH,
        WEB_SEARCH,
    ])

    BASH_TOOLS: Final[frozenset[str]] = frozenset([
        BASH,
        "mcp__bash",  # Potential variant
    ])

    ALL_ALLOWED_TOOLS: Final[list[str]] = [
        GET_SYSTEM_INFO,
        LIST_PROCESSES,
        GET_PROCESS_TREE,
        FIND_PROCESS_BY_NAME,
        CHECK_PORT_BINDING,
        READ_PROC_FILE,
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
        """Check if a tool is a bash tool.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool is a bash tool
        """
        return tool_name in cls.BASH_TOOLS or "bash" in tool_name.lower()
