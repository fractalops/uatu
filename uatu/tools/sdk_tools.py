"""Tool definitions using Claude Agent SDK.

Uses asyncio for non-blocking I/O operations:
- asyncio.create_subprocess_exec() for shell commands
- asyncio.gather() for parallel execution
- asyncio.to_thread() for CPU-bound psutil calls
"""

import asyncio
import json
import os
import pathlib
import platform
from typing import Any

import psutil
from claude_agent_sdk import tool

from uatu.capabilities import ToolCapabilities
from uatu.utils import safe_float, safe_int, safe_str


async def _run_subprocess_async(cmd: list[str], timeout: float = 10.0) -> str:
    """Run a subprocess asynchronously with timeout.

    Uses asyncio.create_subprocess_exec() for non-blocking I/O.

    Args:
        cmd: Command and arguments
        timeout: Timeout in seconds

    Returns:
        stdout output, or empty string on error/timeout
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode().strip()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ""
    except Exception:
        return ""


async def _gather_with_errors(*coros) -> list:
    """Run coroutines in parallel, capturing exceptions as error dicts.

    Args:
        *coros: Coroutines to run

    Returns:
        List of results (or {"error": str} for failed coros)
    """
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [
        {"error": str(r)} if isinstance(r, Exception) else r
        for r in results
    ]

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
    min_cpu_percent = safe_float(min_cpu_percent, 5.0)
    min_memory_mb = safe_float(min_memory_mb, 100.0)

    # Import here to keep logic in existing files
    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import ListProcessesMac

        tool_impl = ListProcessesMac(_capabilities)
    else:
        from uatu.tools.proc_tools import ListProcesses

        tool_impl = ListProcesses(_capabilities)

    result = tool_impl.execute(min_cpu_percent=min_cpu_percent, min_memory_mb=min_memory_mb)

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
    # Defensive handling for SDK quirks (sometimes passes {} or wrong types)
    name = safe_str(name, "")
    if not name:
        return {"content": [{"type": "text", "text": json.dumps({"error": "name parameter is required"}, indent=2)}]}

    if platform.system() == "Darwin":
        from uatu.tools.macos_tools import FindProcessByNameMac

        tool_impl = FindProcessByNameMac(_capabilities)
    else:
        from uatu.tools.command_tools import FindProcessByName

        tool_impl = FindProcessByName(_capabilities)

    result = tool_impl.execute(name=name)

    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# -----------------------------
# Additional diagnostics tools
# -----------------------------


def _expand_path(path: str) -> pathlib.Path:
    """Expand ~ and resolve path."""
    return pathlib.Path(os.path.expanduser(path)).resolve()


async def _scan_directory_sizes_async(path: str, max_depth: int, top_n: int) -> dict[str, Any]:
    """Scan a single directory for sizes (async).

    Uses asyncio subprocess for non-blocking I/O.
    Handles macOS protected directories gracefully.
    """
    root = _expand_path(path)

    # Check if path exists and is accessible
    if not root.exists():
        return {"root": str(root), "entries": [], "error": f"Path does not exist: {root}"}

    is_macos = platform.system() == "Darwin"
    depth_flag = "-d" if is_macos else "--max-depth"
    cmd = ["du", "-h", depth_flag, str(max_depth), str(root)]

    # Longer timeout for large directories (code dirs can take 30s+)
    output = await _run_subprocess_async(cmd, timeout=45.0)

    # Detect permission errors (macOS Full Disk Access)
    if not output or "operation not permitted" in output.lower() or "permission denied" in output.lower():
        # Try to get at least the total size using a different method
        try:
            total_size = await asyncio.to_thread(
                lambda: sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                if root.is_dir() else root.stat().st_size
            )
            size_mb = total_size / (1024 * 1024)
            size_str = f"{size_mb:.1f}MB" if size_mb < 1024 else f"{size_mb/1024:.1f}GB"
            return {
                "root": str(root),
                "entries": [{"size": size_str, "path": str(root)}],
                "note": "Limited access - macOS requires Full Disk Access for detailed scan. "
                        "Use Bash 'du' command instead which has terminal permissions.",
            }
        except (PermissionError, OSError):
            return {
                "root": str(root),
                "entries": [],
                "error": f"Permission denied: {root}. macOS protects this directory. "
                         "Use Bash 'du -sh {root}' which has terminal permissions.",
            }

    entries = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            size, entry = parts
            entries.append({"size": size, "path": entry})
    entries = sorted(entries, key=lambda x: x["size"], reverse=True)[:top_n]
    return {"root": str(root), "entries": entries}


@tool(
    name="get_directory_sizes",
    description=(
        "Summarize directory sizes. Accepts single path OR multiple paths "
        "(comma-separated or array) for PARALLEL scanning. Example: '~/Downloads,~/code,~/me'"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "default": "~",
                "description": "Path(s) to analyze. Comma-separated for multiple: '~/a,~/b,~/c'",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alternative: array of paths to scan in parallel",
            },
            "max_depth": {"type": "integer", "default": 2, "description": "Maximum depth for du summary"},
            "top_n": {"type": "integer", "default": 10, "description": "Top N entries per path"},
        },
        "required": [],
    },
)
async def get_directory_sizes(
    path: str = "~",
    paths: list[str] | None = None,
    max_depth: int = 2,
    top_n: int = 10,
) -> dict[str, Any]:
    path = safe_str(path, "~")
    max_depth = max(0, min(safe_int(max_depth, 2), 5))
    top_n = max(1, min(safe_int(top_n, 10), 50))

    # Build list of paths to scan
    path_list: list[str] = []
    if paths and isinstance(paths, list):
        path_list = [safe_str(p, "") for p in paths if p]
    elif "," in path:
        path_list = [p.strip() for p in path.split(",") if p.strip()]
    else:
        path_list = [path]

    # Scan paths in parallel using asyncio.gather()
    coros = [_scan_directory_sizes_async(p, max_depth, top_n) for p in path_list]
    results = await _gather_with_errors(*coros)

    # Format output
    if len(results) == 1:
        return {"content": [{"type": "text", "text": json.dumps(results[0], indent=2)}]}
    return {"content": [{"type": "text", "text": json.dumps({"scans": results}, indent=2)}]}


async def _find_large_files_async(
    path: str, min_size_mb: float, max_depth: int, top_n: int
) -> dict[str, Any]:
    """Find large files in a single path (async).

    Uses asyncio subprocess for non-blocking I/O.
    Handles macOS protected directories gracefully.
    """
    root = _expand_path(path)

    # Check if path exists
    if not root.exists():
        return {"root": str(root), "files": [], "error": f"Path does not exist: {root}"}

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
    # Longer timeout for large directories
    output = await _run_subprocess_async(find_cmd, timeout=45.0)

    # Detect permission errors
    if "operation not permitted" in output.lower() or "permission denied" in output.lower():
        return {
            "root": str(root),
            "files": [],
            "error": f"Permission denied: {root}. macOS protects this directory. "
                     f"Use Bash 'find {root} -size +{int(min_size_mb)}M' which has terminal permissions.",
        }

    files = [line for line in output.splitlines() if line.strip() and not line.startswith("find:")]
    files = files[: top_n * 3]  # cap before stat

    results = []
    for fpath in files:
        try:
            p = pathlib.Path(fpath)
            stat = await asyncio.to_thread(p.stat)
            size_mb = stat.st_size / (1024 * 1024)
            results.append({"path": str(p), "size_mb": round(size_mb, 2)})
        except Exception:
            continue
    results = sorted(results, key=lambda x: x["size_mb"], reverse=True)[:top_n]
    return {"root": str(root), "files": results}


@tool(
    name="find_large_files",
    description=(
        "Find large files. Accepts single path OR multiple paths "
        "(comma-separated or array) for PARALLEL scanning. Example: '~/Downloads,~/code'"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "default": "~",
                "description": "Path(s) to search. Comma-separated for multiple: '~/a,~/b'",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alternative: array of paths to scan in parallel",
            },
            "min_size_mb": {"type": "number", "default": 100.0, "description": "Minimum file size in MB"},
            "max_depth": {"type": "integer", "default": 4, "description": "Maximum search depth"},
            "top_n": {"type": "integer", "default": 10, "description": "Top N results per path"},
        },
        "required": [],
    },
)
async def find_large_files(
    path: str = "~",
    paths: list[str] | None = None,
    min_size_mb: float = 100.0,
    max_depth: int = 4,
    top_n: int = 10,
) -> dict[str, Any]:
    path = safe_str(path, "~")
    min_size_mb = max(1.0, safe_float(min_size_mb, 100.0))
    max_depth = max(1, min(safe_int(max_depth, 4), 6))
    top_n = max(1, min(safe_int(top_n, 10), 50))

    # Build list of paths
    path_list: list[str] = []
    if paths and isinstance(paths, list):
        path_list = [safe_str(p, "") for p in paths if p]
    elif "," in path:
        path_list = [p.strip() for p in path.split(",") if p.strip()]
    else:
        path_list = [path]

    # Scan paths in parallel using asyncio.gather()
    coros = [_find_large_files_async(p, min_size_mb, max_depth, top_n) for p in path_list]
    results = await _gather_with_errors(*coros)

    # Format output
    if len(results) == 1:
        return {"content": [{"type": "text", "text": json.dumps(results[0], indent=2)}]}
    return {"content": [{"type": "text", "text": json.dumps({"scans": results}, indent=2)}]}


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
    # Normalize inputs using safe utilities
    path = safe_str(path, "~")
    max_depth = max(0, min(safe_int(max_depth, 2), 5))
    min_size_mb = max(10.0, safe_float(min_size_mb, 200.0))
    top_dirs = max(1, min(safe_int(top_dirs, 10), 50))
    top_files = max(0, min(safe_int(top_files, 5), 50))

    root = _expand_path(path)

    # Get disk usage (use to_thread for blocking psutil call)
    usage_payload: dict[str, Any] = {}
    try:
        usage = await asyncio.to_thread(psutil.disk_usage, str(root))
        usage_payload = {
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "percent": usage.percent,
        }
    except Exception:
        usage_payload = {"error": "disk usage unavailable for path"}

    # Run du and find in parallel using asyncio
    is_macos = platform.system() == "Darwin"
    depth_flag = "-d" if is_macos else "--max-depth"
    du_cmd = ["du", "-k", depth_flag, str(max_depth), str(root)]

    find_cmd = [
        "find",
        str(root),
        "-type",
        "f",
        "-size",
        f"+{int(min_size_mb)}M",
        "-maxdepth",
        str(max_depth if max_depth > 0 else 1),
    ] if top_files > 0 else None

    # Run both commands in parallel
    if find_cmd:
        du_output, find_output = await asyncio.gather(
            _run_subprocess_async(du_cmd, timeout=30.0),
            _run_subprocess_async(find_cmd, timeout=30.0),
        )
    else:
        du_output = await _run_subprocess_async(du_cmd, timeout=30.0)
        find_output = ""

    # Parse du output
    directories = []
    for line in du_output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            size_kb = int(parts[0])
            entry_path = parts[1]
            directories.append({"path": entry_path, "size_mb": round(size_kb / 1024, 2)})
    directories = sorted(directories, key=lambda x: x["size_mb"], reverse=True)[:top_dirs]

    # Parse find output and stat files (use to_thread for blocking stat calls)
    large_files = []
    if find_output:
        candidates = [line for line in find_output.splitlines() if line.strip()]
        candidates = candidates[: top_files * 3]

        async def stat_file(fpath: str) -> dict | None:
            try:
                p = pathlib.Path(fpath)
                stat = await asyncio.to_thread(p.stat)
                size_mb = stat.st_size / (1024 * 1024)
                return {"path": str(p), "size_mb": round(size_mb, 2)}
            except Exception:
                return None

        stat_results = await asyncio.gather(*[stat_file(f) for f in candidates])
        large_files = [r for r in stat_results if r is not None]
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
    top_n = max(1, min(safe_int(top_n, 10), 30))

    # First pass: prime cpu_percent for all processes (interval=None returns cached value)
    # We need to call it once to establish a baseline
    for p in psutil.process_iter():
        try:
            p.cpu_percent(interval=None)
        except Exception:
            pass

    # Brief sleep to allow CPU measurement window
    import asyncio
    await asyncio.sleep(0.2)

    # Second pass: collect actual CPU percentages
    procs = []
    for p in psutil.process_iter(attrs=["pid", "name", "username"]):
        try:
            info = p.as_dict(attrs=["pid", "name", "username"])
            # Now cpu_percent returns meaningful values
            info["cpu_percent"] = safe_float(p.cpu_percent(interval=None), 0.0)
            mem = p.memory_info()
            info["rss_mb"] = round(safe_float(mem.rss, 0.0) / (1024 * 1024), 2)
            procs.append(info)
        except Exception:
            continue
    procs_by_cpu = sorted(procs, key=lambda x: safe_float(x.get("cpu_percent", 0), 0.0), reverse=True)[:top_n]
    procs_by_mem = sorted(procs, key=lambda x: safe_float(x.get("rss_mb", 0), 0.0), reverse=True)[:top_n]
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
