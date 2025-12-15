"""Tool definitions using Claude Agent SDK."""

import json
import os
import pathlib
import platform
import subprocess
from typing import Any

import psutil
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


# -----------------------------
# Additional diagnostics tools
# -----------------------------


def _expand_path(path: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(path)).resolve()


def _run_subprocess(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


@tool(
    name="get_directory_sizes",
    description="Summarize directory sizes under a path with bounded depth. Returns top entries by size.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "~", "description": "Root path to analyze"},
            "max_depth": {"type": "integer", "default": 2, "description": "Maximum depth for du summary"},
            "top_n": {"type": "integer", "default": 10, "description": "Top N entries to return"},
        },
        "required": [],
    },
)
async def get_directory_sizes(path: str = "~", max_depth: int = 2, top_n: int = 10) -> dict[str, Any]:
    if isinstance(path, dict) or path is None:
        path = "~"
    if isinstance(max_depth, dict) or max_depth is None:
        max_depth = 2
    if isinstance(top_n, dict) or top_n is None:
        top_n = 10

    root = _expand_path(str(path))
    max_depth = max(0, min(int(max_depth), 5))
    top_n = max(1, min(int(top_n), 50))

    is_macos = platform.system() == "Darwin"
    depth_flag = "-d" if is_macos else "--max-depth"
    cmd = ["du", "-h", depth_flag, str(max_depth), str(root)]
    output = _run_subprocess(cmd, timeout=12.0)
    entries = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            size, entry = parts
            entries.append({"size": size, "path": entry})
    entries = sorted(entries, key=lambda x: x["size"], reverse=True)[:top_n]
    return {"content": [{"type": "text", "text": json.dumps({"root": str(root), "entries": entries}, indent=2)}]}


@tool(
    name="find_large_files",
    description="Find large files under a path with bounded depth and size threshold.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "~", "description": "Root path to search"},
            "min_size_mb": {"type": "number", "default": 100.0, "description": "Minimum file size in MB"},
            "max_depth": {"type": "integer", "default": 4, "description": "Maximum search depth"},
            "top_n": {"type": "integer", "default": 10, "description": "Top N results to return"},
        },
        "required": [],
    },
)
async def find_large_files(
    path: str = "~", min_size_mb: float = 100.0, max_depth: int = 4, top_n: int = 10
) -> dict[str, Any]:
    if isinstance(path, dict) or path is None:
        path = "~"
    if isinstance(min_size_mb, dict) or min_size_mb is None:
        min_size_mb = 100.0
    if isinstance(max_depth, dict) or max_depth is None:
        max_depth = 4
    if isinstance(top_n, dict) or top_n is None:
        top_n = 10

    root = _expand_path(str(path))
    min_size_mb = max(1.0, float(min_size_mb))
    max_depth = max(1, min(int(max_depth), 6))
    top_n = max(1, min(int(top_n), 50))

    # Use find with -maxdepth if available
    find_cmd = [
        "find",
        str(root),
        "-type",
        "f",
        "-size",
        f"+{int(min_size_mb)}M",
        "-maxdepth",
        str(max_depth),
    ]
    output = _run_subprocess(find_cmd, timeout=15.0)
    files = [line for line in output.splitlines() if line.strip()]
    files = files[: top_n * 3]  # cap before stat

    # Stat sizes
    results = []
    for fpath in files:
        try:
            p = pathlib.Path(fpath)
            size_mb = p.stat().st_size / (1024 * 1024)
            results.append({"path": str(p), "size_mb": round(size_mb, 2)})
        except Exception:
            continue
    results = sorted(results, key=lambda x: x["size_mb"], reverse=True)[:top_n]
    return {"content": [{"type": "text", "text": json.dumps({"root": str(root), "files": results}, indent=2)}]}


@tool(
    name="disk_scan_summary",
    description=(
        "Summarize disk usage for a path: filesystem usage, top directories by size, "
        "and large files with bounded depth."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "~", "description": "Root path to scan"},
            "max_depth": {"type": "integer", "default": 2, "description": "Max depth for directory summary"},
            "min_size_mb": {"type": "number", "default": 200.0, "description": "Minimum size for large files"},
            "top_dirs": {"type": "integer", "default": 10, "description": "Top directories to return"},
            "top_files": {"type": "integer", "default": 5, "description": "Top large files to return"},
        },
        "required": [],
    },
)
async def disk_scan_summary(
    path: str = "~",
    max_depth: int = 2,
    min_size_mb: float = 200.0,
    top_dirs: int = 10,
    top_files: int = 5,
) -> dict[str, Any]:
    # Defensive handling for SDK quirks (sometimes passes {} or wrong types)
    if isinstance(path, dict) or path is None:
        path = "~"
    if isinstance(max_depth, dict) or max_depth is None:
        max_depth = 2
    if isinstance(min_size_mb, dict) or min_size_mb is None:
        min_size_mb = 200.0
    if isinstance(top_dirs, dict) or top_dirs is None:
        top_dirs = 10
    if isinstance(top_files, dict) or top_files is None:
        top_files = 5

    root = _expand_path(str(path))
    max_depth = max(0, min(int(max_depth), 5))
    min_size_mb = max(10.0, float(min_size_mb))
    top_dirs = max(1, min(int(top_dirs), 50))
    top_files = max(0, min(int(top_files), 50))

    usage_payload: dict[str, Any] = {}
    try:
        usage = psutil.disk_usage(str(root))
        usage_payload = {
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "percent": usage.percent,
        }
    except Exception:
        usage_payload = {"error": "disk usage unavailable for path"}

    is_macos = platform.system() == "Darwin"
    depth_flag = "-d" if is_macos else "--max-depth"
    du_cmd = ["du", "-k", depth_flag, str(max_depth), str(root)]
    du_output = _run_subprocess(du_cmd, timeout=12.0)

    directories = []
    for line in du_output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            size_kb = int(parts[0])
            entry_path = parts[1]
            directories.append({"path": entry_path, "size_mb": round(size_kb / 1024, 2)})
    directories = sorted(directories, key=lambda x: x["size_mb"], reverse=True)[:top_dirs]

    large_files = []
    if top_files > 0:
        find_cmd = [
            "find",
            str(root),
            "-type",
            "f",
            "-size",
            f"+{int(min_size_mb)}M",
            "-maxdepth",
            str(max_depth if max_depth > 0 else 1),
        ]
        find_output = _run_subprocess(find_cmd, timeout=12.0)
        candidates = [line for line in find_output.splitlines() if line.strip()]
        candidates = candidates[: top_files * 3]
        for fpath in candidates:
            try:
                p = pathlib.Path(fpath)
                size_mb = p.stat().st_size / (1024 * 1024)
                large_files.append({"path": str(p), "size_mb": round(size_mb, 2)})
            except Exception:
                continue
        large_files = sorted(large_files, key=lambda x: x["size_mb"], reverse=True)[:top_files]

    payload = {
        "root": str(root),
        "usage": usage_payload,
        "top_directories": directories,
        "large_files": large_files,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    name="get_connection_summary",
    description="Summarize network connections by state, top ports, and top remote IPs without raw dumps.",
    input_schema={"type": "object", "properties": {}, "required": []},
)
async def get_connection_summary(*args, **kwargs) -> dict[str, Any]:
    states: dict[str, int] = {}
    ports: dict[str, int] = {}
    remotes: dict[str, int] = {}
    try:
        conns = psutil.net_connections(kind="inet")
        for c in conns:
            state = c.status or "UNKNOWN"
            states[state] = states.get(state, 0) + 1
            if c.laddr and c.laddr.port:
                port_key = str(c.laddr.port)
                ports[port_key] = ports.get(port_key, 0) + 1
            if c.raddr and c.raddr.ip:
                remotes[c.raddr.ip] = remotes.get(c.raddr.ip, 0) + 1
    except Exception:
        pass
    top_ports = sorted(ports.items(), key=lambda x: x[1], reverse=True)[:10]
    top_remotes = sorted(remotes.items(), key=lambda x: x[1], reverse=True)[:10]
    payload = {
        "states": states,
        "top_ports": [{"port": p, "count": c} for p, c in top_ports],
        "top_remote_ips": [{"ip": ip, "count": c} for ip, c in top_remotes],
        "total_connections": sum(states.values()),
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    name="get_resource_hogs",
    description="Return top processes by CPU and memory with limits to avoid noise.",
    input_schema={
        "type": "object",
        "properties": {
            "top_n": {"type": "integer", "default": 10, "description": "Number of processes to return"},
        },
        "required": [],
    },
)
async def get_resource_hogs(top_n: int = 10) -> dict[str, Any]:
    if isinstance(top_n, dict) or top_n is None:
        top_n = 10
    top_n = max(1, min(int(top_n or 10), 30))

    def _num(val: Any, default: float = 0.0) -> float:
        try:
            return float(val)
        except Exception:
            return default

    procs = []
    for p in psutil.process_iter(attrs=["pid", "name", "username"]):
        try:
            info = p.as_dict(attrs=["pid", "name", "username"])
            info["cpu_percent"] = _num(p.cpu_percent(interval=0.0), 0.0)
            mem = p.memory_info()
            info["rss_mb"] = round(_num(mem.rss, 0.0) / (1024 * 1024), 2)
            procs.append(info)
        except Exception:
            continue
    procs_by_cpu = sorted(procs, key=lambda x: _num(x.get("cpu_percent", 0), 0.0), reverse=True)[:top_n]
    procs_by_mem = sorted(procs, key=lambda x: _num(x.get("rss_mb", 0), 0.0), reverse=True)[:top_n]
    payload = {"top_cpu": procs_by_cpu, "top_memory": procs_by_mem}
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    name="get_process_threads",
    description="Get thread count and basic thread info for a process.",
    input_schema={
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID"},
            "limit": {"type": "integer", "default": 10, "description": "Max threads to list"},
        },
        "required": ["pid"],
    },
)
async def get_process_threads(pid: int, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    try:
        proc = psutil.Process(pid)
        threads = proc.threads()[:limit]
        payload = {
            "pid": pid,
            "num_threads": proc.num_threads(),
            "threads": [{"id": t.id, "user_time": t.user_time, "system_time": t.system_time} for t in threads],
        }
    except Exception as e:
        payload = {"pid": pid, "error": str(e)}
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    name="get_process_files",
    description="List open files for a process with a limit to avoid noise.",
    input_schema={
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID"},
            "limit": {"type": "integer", "default": 20, "description": "Max open files to list"},
        },
        "required": ["pid"],
    },
)
async def get_process_files(pid: int, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    try:
        proc = psutil.Process(pid)
        files = proc.open_files()[:limit]
        payload = {
            "pid": pid,
            "count": len(files),
            "files": [{"path": f.path, "fd": f.fd} for f in files],
        }
    except Exception as e:
        payload = {"pid": pid, "error": str(e)}
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


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
