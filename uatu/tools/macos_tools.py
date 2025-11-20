"""macOS-specific tools using ps, sysctl, and other BSD utilities."""

import platform
import subprocess
from typing import Any

from uatu.tools.base import Tool, ToolMetadata


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system() == "Darwin"


class ListProcessesMac(Tool):
    """List processes on macOS using ps."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="list_processes",
            description="List all running processes with PID, CPU, memory, and command.",
            tier=1,
            requires_commands=["ps"],
        )

    def is_available(self) -> bool:
        """Only available on macOS with ps."""
        return is_macos() and self.capabilities.has_ps

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "min_cpu_percent": {
                    "type": "number",
                    "description": "Only return processes above this CPU % (default: 5.0)",
                    "default": 5.0,
                },
                "min_memory_mb": {
                    "type": "number",
                    "description": "Only return processes above this memory MB (default: 100.0)",
                    "default": 100.0,
                },
            },
        }

    def execute(self, min_cpu_percent: float = 5.0, min_memory_mb: float = 100.0) -> list[dict[str, Any]]:
        """List all processes using macOS ps."""
        try:
            # macOS ps format
            result = subprocess.run(
                ["ps", "-eo", "pid,user,%cpu,%mem,state,command"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            processes = []
            for line in result.stdout.splitlines()[1:]:  # Skip header
                parts = line.split(None, 5)
                if len(parts) >= 6:
                    try:
                        pid = int(parts[0])
                        user = parts[1]
                        # Handle locale-specific decimal separators (comma vs period)
                        cpu_percent = float(parts[2].replace(",", "."))
                        mem_percent = float(parts[3].replace(",", "."))
                        state = parts[4]
                        cmdline = parts[5]

                        # Estimate memory in MB (rough approximation)
                        # Get system memory and calculate
                        memory_mb = mem_percent * self._get_total_memory_mb() / 100

                        # Apply filters
                        if cpu_percent < min_cpu_percent:
                            continue
                        if memory_mb < min_memory_mb:
                            continue

                        processes.append(
                            {
                                "pid": pid,
                                "user": user,
                                "cpu_percent": cpu_percent,
                                "memory_mb": memory_mb,
                                "memory_percent": mem_percent,
                                "state": state,
                                "cmdline": cmdline,
                                "name": cmdline.split()[0].split("/")[-1] if cmdline else "?",
                            }
                        )
                    except (ValueError, IndexError):
                        continue

            return sorted(processes, key=lambda x: x["pid"])

        except subprocess.SubprocessError:
            return []

    def _get_total_memory_mb(self) -> float:
        """Get total system memory in MB using sysctl."""
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            bytes_total = int(result.stdout.strip())
            return bytes_total / 1024 / 1024
        except (subprocess.SubprocessError, ValueError):
            return 8192  # Default fallback


class GetSystemInfoMac(Tool):
    """Get system information on macOS using sysctl and vm_stat."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="get_system_info",
            description="Get system CPU, memory, and load information on macOS.",
            tier=1,
            requires_commands=["sysctl"],
        )

    def is_available(self) -> bool:
        """Only available on macOS."""
        return is_macos()

    def get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self) -> dict[str, Any]:
        """Get system information using macOS tools."""
        return {
            "memory": self._get_memory_info(),
            "load": self._get_load_average(),
            "cpu_count": self._get_cpu_count(),
        }

    def _get_memory_info(self) -> dict[str, Any]:
        """Get memory info using vm_stat."""
        try:
            # Get total memory
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            total_bytes = int(result.stdout.strip())
            total_mb = total_bytes / 1024 / 1024

            # Get vm_stat for usage
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # Parse vm_stat (page size and statistics)
            pages_free = 0
            pages_active = 0
            pages_inactive = 0
            pages_wired = 0
            page_size = 4096  # Default

            for line in result.stdout.splitlines():
                if "page size of" in line:
                    page_size = int(line.split()[-2])
                elif "Pages free:" in line:
                    pages_free = int(line.split()[-1].rstrip("."))
                elif "Pages active:" in line:
                    pages_active = int(line.split()[-1].rstrip("."))
                elif "Pages inactive:" in line:
                    pages_inactive = int(line.split()[-1].rstrip("."))
                elif "Pages wired down:" in line:
                    pages_wired = int(line.split()[-1].rstrip("."))

            # Calculate memory usage
            used_pages = pages_active + pages_inactive + pages_wired
            used_mb = (used_pages * page_size) / 1024 / 1024
            available_mb = (pages_free * page_size) / 1024 / 1024

            return {
                "total_mb": total_mb,
                "used_mb": used_mb,
                "available_mb": available_mb,
                "percent": (used_mb / total_mb * 100) if total_mb > 0 else 0,
            }

        except (subprocess.SubprocessError, ValueError):
            return {
                "total_mb": 0,
                "used_mb": 0,
                "available_mb": 0,
                "percent": 0,
            }

    def _get_load_average(self) -> dict[str, float]:
        """Get load average using sysctl."""
        try:
            result = subprocess.run(
                ["sysctl", "-n", "vm.loadavg"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Format: { 1.23 2.34 3.45 } or { 1,23 2,34 3,45 } depending on locale
            loads = result.stdout.strip().strip("{}").split()
            # Handle both dot and comma decimal separators
            return {
                "1min": float(loads[0].replace(",", ".")),
                "5min": float(loads[1].replace(",", ".")),
                "15min": float(loads[2].replace(",", ".")),
            }
        except (subprocess.SubprocessError, ValueError, IndexError):
            return {"1min": 0.0, "5min": 0.0, "15min": 0.0}

    def _get_cpu_count(self) -> int:
        """Get CPU count using sysctl."""
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.ncpu"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return int(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            return 1


class GetProcessTreeMac(Tool):
    """Get process tree on macOS using ps."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="get_process_tree",
            description="Get parent-child process relationships on macOS.",
            tier=1,
            requires_commands=["ps"],
        )

    def is_available(self) -> bool:
        """Only available on macOS with ps."""
        return is_macos() and self.capabilities.has_ps

    def get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self) -> dict[str, Any]:
        """Build process tree using ps."""
        try:
            # Get all processes with parent PID
            result = subprocess.run(
                ["ps", "-eo", "pid,ppid,user,command"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            processes = {}
            for line in result.stdout.splitlines()[1:]:  # Skip header
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    try:
                        pid = int(parts[0])
                        ppid = int(parts[1])
                        user = parts[2]
                        cmdline = parts[3]

                        processes[pid] = {
                            "pid": pid,
                            "ppid": ppid,
                            "user": user,
                            "cmdline": cmdline[:60],
                        }
                    except ValueError:
                        continue

            # Build tree structure
            tree = self._build_tree(processes)

            return {
                "total_processes": len(processes),
                "tree": tree,
            }

        except subprocess.SubprocessError:
            return {
                "total_processes": 0,
                "tree": [],
            }

    def _build_tree(self, processes: dict[int, dict]) -> list[str]:
        """Format process tree."""
        lines = []
        visited = set()

        def add_process(pid: int, depth: int) -> None:
            if pid in visited or pid not in processes:
                return

            visited.add(pid)
            info = processes[pid]
            indent = "  " * depth
            lines.append(f"{indent}{pid}: {info['cmdline']}")

            # Find children
            children = [p for p in processes.values() if p["ppid"] == pid]
            for child in sorted(children, key=lambda x: x["pid"]):
                add_process(child["pid"], depth + 1)

        # Start with init-like processes (ppid=0 or ppid=1)
        roots = [p for p in processes.values() if p["ppid"] <= 1]
        for root in sorted(roots, key=lambda x: x["pid"]):
            add_process(root["pid"], 0)

        return lines


class FindProcessByNameMac(Tool):
    """Find processes by name on macOS using ps and grep."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="find_process_by_name",
            description="Find all processes matching a name pattern on macOS.",
            tier=1,
            requires_commands=["ps"],
        )

    def is_available(self) -> bool:
        """Only available on macOS with ps."""
        return is_macos() and self.capabilities.has_ps

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
        """Find processes by name using ps."""
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,user,command"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            processes = []
            for line in result.stdout.splitlines()[1:]:  # Skip header
                if name.lower() in line.lower():
                    parts = line.split(None, 2)
                    if len(parts) >= 3:
                        try:
                            processes.append(
                                {
                                    "pid": int(parts[0]),
                                    "user": parts[1],
                                    "cmdline": parts[2],
                                    "name": parts[2].split()[0].split("/")[-1] if parts[2] else "?",
                                }
                            )
                        except ValueError:
                            continue

            return processes

        except subprocess.SubprocessError:
            return []
