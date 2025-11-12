"""Tier 1+ tools that use system commands with /proc fallbacks."""

import subprocess
from typing import Any

from uatu.tools.base import Tool, ToolMetadata
from uatu.tools.proc_tools import ListProcesses


class FindProcessByName(Tool):
    """Find processes by name using pgrep or /proc scan."""

    @property
    def metadata(self) -> ToolMetadata:
        # This tool always works - uses ps if available, /proc otherwise
        return ToolMetadata(
            name="find_process_by_name",
            description="Find all processes matching a name pattern.",
            tier=1,
            requires_proc=True,  # Fallback requires /proc
        )

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Process name or pattern to search for",
                }
            },
            "required": ["name"],
        }

    def execute(self, name: str) -> list[dict[str, Any]]:
        """Find processes by name."""
        # Try ps first (cleaner output)
        if self.capabilities.has_ps:
            return self._find_via_ps(name)

        # Fallback to /proc
        return self._find_via_proc(name)

    def _find_via_ps(self, name: str) -> list[dict[str, Any]]:
        """Use ps command."""
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,user,comm,args"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            processes = []
            for line in result.stdout.splitlines()[1:]:  # Skip header
                if name.lower() in line.lower():
                    parts = line.split(None, 3)
                    if len(parts) >= 4:
                        processes.append(
                            {
                                "pid": int(parts[0]),
                                "user": parts[1],
                                "name": parts[2],
                                "cmdline": parts[3],
                            }
                        )

            return processes

        except (subprocess.SubprocessError, ValueError):
            # Fall back to /proc
            return self._find_via_proc(name)

    def _find_via_proc(self, name: str) -> list[dict[str, Any]]:
        """Scan /proc directories."""
        # Use the Tier 0 list_processes tool
        list_tool = ListProcesses(self.capabilities)
        all_processes = list_tool.execute()

        # Filter by name
        return [p for p in all_processes if name.lower() in p["name"].lower() or name.lower() in p["cmdline"].lower()]


class CheckPortBinding(Tool):
    """Check what process is using a specific port."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="check_port_binding",
            description="Check which process (if any) is listening on a specific port.",
            tier=2,  # Prefers ss/netstat, can use /proc/net/tcp
            requires_proc=True,
        )

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port number to check",
                }
            },
            "required": ["port"],
        }

    def execute(self, port: int) -> dict[str, Any]:
        """Check port binding."""
        # Try ss (modern, fast)
        if self.capabilities.has_ss:
            return self._check_via_ss(port)

        # Try netstat (older, slower)
        if self.capabilities.has_netstat:
            return self._check_via_netstat(port)

        # Fallback to /proc/net/tcp
        return self._check_via_proc(port)

    def _check_via_ss(self, port: int) -> dict[str, Any]:
        """Use ss command."""
        try:
            result = subprocess.run(
                ["ss", "-ltnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                if len(lines) > 1:  # Has header + data
                    # Parse process info from output
                    # Format: ... users:(("process",pid=123,fd=4))
                    return {
                        "port": port,
                        "in_use": True,
                        "details": lines[1],
                    }

            return {"port": port, "in_use": False}

        except subprocess.SubprocessError:
            return self._check_via_proc(port)

    def _check_via_netstat(self, port: int) -> dict[str, Any]:
        """Use netstat command."""
        try:
            result = subprocess.run(
                ["netstat", "-ltnp"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTEN" in line:
                    return {
                        "port": port,
                        "in_use": True,
                        "details": line.strip(),
                    }

            return {"port": port, "in_use": False}

        except subprocess.SubprocessError:
            return self._check_via_proc(port)

    def _check_via_proc(self, port: int) -> dict[str, Any]:
        """Parse /proc/net/tcp."""
        from pathlib import Path

        try:
            # /proc/net/tcp format: port is in hex
            hex_port = f"{port:04X}"

            tcp_file = Path("/proc/net/tcp").read_text()
            for line in tcp_file.splitlines()[1:]:  # Skip header
                parts = line.split()
                if len(parts) > 1:
                    local_address = parts[1]
                    if f":{hex_port}" in local_address.upper():
                        # Check if listening (state 0A = LISTEN)
                        state = parts[3]
                        if state == "0A":
                            return {
                                "port": port,
                                "in_use": True,
                                "details": f"Port {port} is listening",
                            }

            return {"port": port, "in_use": False}

        except Exception as e:
            return {
                "port": port,
                "in_use": False,
                "error": str(e),
            }
