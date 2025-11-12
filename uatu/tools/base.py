"""Base classes for the tool system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from uatu.capabilities import ToolCapabilities


@dataclass
class ToolMetadata:
    """Metadata describing a tool's requirements and capabilities."""

    name: str
    description: str
    tier: int  # 0=kernel, 1=core utils, 2=admin tools, 3=enhanced
    requires_proc: bool = False
    requires_commands: list[str] = None
    requires_root: bool = False
    works_in_container: bool = True

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.requires_commands is None:
            self.requires_commands = []


class Tool(ABC):
    """
    Base class for all Uatu tools.

    Tools are atomic operations that return raw data.
    The agent interprets and combines tool results.
    """

    def __init__(self, capabilities: ToolCapabilities):
        """Initialize tool with system capabilities."""
        self.capabilities = capabilities

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Return tool metadata."""
        pass

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """
        Execute the tool and return raw data.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Raw data (dict, list, str, etc.)
        """
        pass

    def is_available(self) -> bool:
        """
        Check if this tool can run on the current system.

        Returns:
            True if tool can execute
        """
        meta = self.metadata

        # Check /proc requirement
        if meta.requires_proc and not self.capabilities.has_proc:
            return False

        # Check command requirements
        for cmd in meta.requires_commands:
            if not getattr(self.capabilities, f"has_{cmd}", False):
                return False

        # Check root requirement
        if meta.requires_root and not self.capabilities.is_root:
            return False

        # Check container compatibility
        if not meta.works_in_container and self.capabilities.in_container:
            return False

        return True

    def get_claude_definition(self) -> dict[str, Any]:
        """
        Get tool definition for Claude API.

        Returns:
            Tool definition dict for Claude's tool calling
        """
        meta = self.metadata

        # Build description with tier info
        description = meta.description

        if meta.tier == 0:
            description += " (Tier 0: Always available)"
        elif meta.tier == 3:
            description += f" (Tier 3: Requires {', '.join(meta.requires_commands)})"

        if not meta.works_in_container:
            description += " [May not work in containers]"

        if meta.requires_root:
            description += " [Requires root]"

        return {
            "name": meta.name,
            "description": description,
            "input_schema": self.get_input_schema(),
        }

    @abstractmethod
    def get_input_schema(self) -> dict[str, Any]:
        """
        Get JSON schema for tool parameters.

        Returns:
            JSON schema dict
        """
        pass


class ToolRegistry:
    """Registry of all available tools."""

    def __init__(self, capabilities: ToolCapabilities):
        """Initialize registry with system capabilities."""
        self.capabilities = capabilities
        self.tools: dict[str, Tool] = {}

    def register(self, tool_class: type[Tool]) -> None:
        """Register a tool class."""
        tool = tool_class(self.capabilities)
        if tool.is_available():
            self.tools[tool.metadata.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self.tools.get(name)

    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a tool by name."""
        tool = self.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Tool not available: {tool_name}")
        return tool.execute(**kwargs)

    def get_claude_tools(self) -> list[dict[str, Any]]:
        """Get all tool definitions for Claude API."""
        return [tool.get_claude_definition() for tool in self.tools.values()]

    def list_available_tools(self) -> list[str]:
        """List names of all available tools."""
        return list(self.tools.keys())
