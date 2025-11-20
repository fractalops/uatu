"""Tier 0 tools that work by reading /proc directly (no dependencies)."""

from pathlib import Path
from typing import Any

from uatu.tools.base import Tool, ToolMetadata


class ReadProcFile(Tool):
    """
    Read any file from /proc or /sys filesystem.

    This is the lowest-level escape hatch - like my Bash tool.
    Always works if /proc is mounted.
    """

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="read_proc_file",
            description="Read a file from /proc or /sys filesystem directly. Low-level access to kernel data.",
            tier=0,
            requires_proc=True,
        )

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to file (e.g., '/proc/meminfo', '/proc/123/status')",
                }
            },
            "required": ["path"],
        }

    def execute(self, path: str) -> str:
        """Read and return file contents."""
        file_path = Path(path)

        # Security: only allow /proc and /sys
        if not str(file_path).startswith(("/proc", "/sys")):
            raise ValueError("Only /proc and /sys paths allowed")

        try:
            return file_path.read_text()
        except FileNotFoundError:
            return f"File not found: {path}"
        except PermissionError:
            return f"Permission denied: {path}"


class ListProcesses(Tool):
    """
    List all running processes by scanning /proc.

    Pure Python implementation - no external commands needed.
    """

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="list_processes",
            description="List all running processes with PID, name, state, and basic stats. "
            "Works by reading /proc directly.",
            tier=0,
            requires_proc=True,
        )

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
        """List all processes."""
        processes = []

        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue

            try:
                pid = int(pid_dir.name)
                proc_info = self._read_process_info(pid)

                # Apply filters
                if proc_info["cpu_percent"] < min_cpu_percent:
                    continue
                if proc_info["memory_mb"] < min_memory_mb:
                    continue

                processes.append(proc_info)

            except (FileNotFoundError, PermissionError):
                # Process may have exited or we don't have permission
                continue

        return sorted(processes, key=lambda x: x["pid"])

    def _read_process_info(self, pid: int) -> dict[str, Any]:
        """Read process information from /proc/[pid]/."""
        base_path = Path(f"/proc/{pid}")

        # Read /proc/[pid]/status
        status = self._parse_status(base_path / "status")

        # Read /proc/[pid]/cmdline
        try:
            cmdline = (base_path / "cmdline").read_text().replace("\x00", " ").strip()
        except Exception:
            cmdline = ""

        # Read /proc/[pid]/stat for timing info
        try:
            stat = (base_path / "stat").read_text().split()
            state = stat[2]  # Process state
        except Exception:
            state = "?"

        return {
            "pid": pid,
            "name": status.get("Name", "?"),
            "state": state,
            "user": status.get("Uid", "?").split()[0],  # Real UID
            "memory_mb": int(status.get("VmRSS", "0").split()[0]) / 1024 if "VmRSS" in status else 0,
            "cpu_percent": 0.0,  # TODO: Calculate from /proc/[pid]/stat
            "threads": int(status.get("Threads", "0")),
            "cmdline": cmdline or status.get("Name", "?"),
        }

    def _parse_status(self, status_file: Path) -> dict[str, str]:
        """Parse /proc/[pid]/status file."""
        status = {}
        try:
            for line in status_file.read_text().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    status[key.strip()] = value.strip()
        except Exception:
            pass
        return status


class GetSystemInfo(Tool):
    """Get system-wide resource information from /proc."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="get_system_info",
            description="Get system CPU, memory, and load information from /proc.",
            tier=0,
            requires_proc=True,
        )

    def get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self) -> dict[str, Any]:
        """Get system information."""
        return {
            "memory": self._get_memory_info(),
            "load": self._get_load_average(),
            "uptime": self._get_uptime(),
        }

    def _get_memory_info(self) -> dict[str, Any]:
        """Parse /proc/meminfo."""
        meminfo = {}
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    # Extract number (strip ' kB')
                    value_kb = int(value.strip().split()[0])
                    meminfo[key.strip()] = value_kb
        except Exception:
            return {}

        total_mb = meminfo.get("MemTotal", 0) / 1024
        available_mb = meminfo.get("MemAvailable", 0) / 1024
        used_mb = total_mb - available_mb

        return {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "available_mb": available_mb,
            "percent": (used_mb / total_mb * 100) if total_mb > 0 else 0,
        }

    def _get_load_average(self) -> dict[str, float]:
        """Parse /proc/loadavg."""
        try:
            loadavg = Path("/proc/loadavg").read_text().split()
            return {
                "1min": float(loadavg[0]),
                "5min": float(loadavg[1]),
                "15min": float(loadavg[2]),
            }
        except Exception:
            return {"1min": 0.0, "5min": 0.0, "15min": 0.0}

    def _get_uptime(self) -> float:
        """Parse /proc/uptime."""
        try:
            uptime = Path("/proc/uptime").read_text().split()[0]
            return float(uptime)
        except Exception:
            return 0.0


class GetProcessTree(Tool):
    """Build process tree by reading parent PIDs from /proc."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="get_process_tree",
            description="Get parent-child process relationships. Returns process tree structure.",
            tier=0,
            requires_proc=True,
        )

    def get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self) -> dict[str, Any]:
        """Build process tree."""
        processes = {}
        tree = {"children": {}}

        # First pass: collect all processes
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue

            try:
                pid = int(pid_dir.name)
                stat = (Path(f"/proc/{pid}") / "stat").read_text()

                # Parse stat file
                # Format: pid (name) state ppid ...
                parts = stat.split(")")
                name = parts[0].split("(")[1]
                stats = parts[1].split()
                ppid = int(stats[1])

                cmdline = (Path(f"/proc/{pid}") / "cmdline").read_text().replace("\x00", " ").strip()

                processes[pid] = {
                    "pid": pid,
                    "ppid": ppid,
                    "name": name,
                    "cmdline": cmdline or name,
                }

            except Exception:
                continue

        # Second pass: build tree
        for pid, info in processes.items():
            ppid = info["ppid"]

            # Root process (ppid=0) or orphan
            if ppid not in processes:
                tree["children"][pid] = {
                    "info": info,
                    "children": {},
                }
            else:
                # Add to parent
                if ppid not in tree["children"]:
                    tree["children"][ppid] = {
                        "info": processes[ppid],
                        "children": {},
                    }

        return {
            "total_processes": len(processes),
            "tree": self._format_tree(tree),
        }

    def _format_tree(self, node: dict[str, Any], depth: int = 0) -> list[str]:
        """Format tree as human-readable lines."""
        lines = []

        for pid, data in sorted(node["children"].items()):
            info = data["info"]
            indent = "  " * depth
            lines.append(f"{indent}{info['pid']}: {info['cmdline'][:60]}")

            # Recurse for children
            if data["children"]:
                lines.extend(self._format_tree(data, depth + 1))

        return lines
