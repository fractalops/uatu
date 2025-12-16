"""Tool result preview formatter.

Provides minimalistic previews of tool execution results to give users
visibility into what data was retrieved without overwhelming the UI.
"""

from typing import Any

from uatu.utils import safe_float


class ToolPreviewFormatter:
    """Formats tool results into minimal previews."""

    MAX_PREVIEW_LENGTH = 90  # Keep inline summaries short
    MAX_LINES_TO_SHOW = 3  # Inline summaries only show a few lines

    # Severity indicators using Rich markup for colored output
    # These render as colored symbols in Rich console
    SEVERITY_CRIT = "[bold red] ●[/]"  # Red filled circle for critical
    SEVERITY_WARN = "[yellow] ●[/]"  # Yellow filled circle for warning
    SEVERITY_OK = "[green dim] ·[/]"  # Subtle green dot for OK (optional)

    @classmethod
    def _severity(cls, value: float, warn_threshold: float, crit_threshold: float) -> str:
        """Return a colored severity indicator based on thresholds.

        Args:
            value: The metric value to check
            warn_threshold: Value above this triggers warning
            crit_threshold: Value above this triggers critical

        Returns:
            Rich-formatted severity indicator string
        """
        if value > crit_threshold:
            return cls.SEVERITY_CRIT
        elif value > warn_threshold:
            return cls.SEVERITY_WARN
        return ""  # No indicator for normal values (cleaner)

    @classmethod
    def format_preview(cls, tool_name: str, tool_response: Any) -> str | None:
        """Format a tool response into a minimal preview string.

        Args:
            tool_name: Name of the tool that was executed
            tool_response: The tool's response data

        Returns:
            Formatted preview string, or None if no preview needed
        """
        # Unwrap MCP content format: [{'type': 'text', 'text': '...'}]
        unwrapped_response = cls._unwrap_mcp_content(tool_response)

        # Handle Bash tool results
        if tool_name == "Bash" or "bash" in tool_name.lower():
            return cls._format_bash_preview(unwrapped_response)

        # Handle MCP tool results
        if tool_name.startswith("mcp__"):
            return cls._format_mcp_preview(tool_name, unwrapped_response)

        # Handle network tools
        if tool_name in ("WebFetch", "WebSearch"):
            return cls._format_network_preview(tool_name, unwrapped_response)

        # Handle Skill invocations
        if tool_name == "Skill":
            return cls._format_skill_preview(unwrapped_response)

        # Default: show type and size
        return cls._format_default_preview(unwrapped_response)

    @classmethod
    def _unwrap_mcp_content(cls, response: Any) -> Any:
        """Unwrap MCP content format if present.

        MCP responses come as: [{'type': 'text', 'text': 'actual data'}]
        This extracts the actual data.
        """
        if isinstance(response, list) and len(response) > 0:
            first_item = response[0]
            if isinstance(first_item, dict) and "type" in first_item and "text" in first_item:
                # This is MCP content format - extract the text
                text = first_item["text"]
                # Try to parse as JSON if it looks like JSON
                if text.strip().startswith(("{", "[")):
                    try:
                        import json
                        return json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        return text
                return text
        return response

    @classmethod
    def _format_bash_preview(cls, response: Any) -> str:
        """Format Bash command output preview.

        Shows line count and first line of output (inline).
        """
        if not response:
            return "✓ No output"

        output = ""

        # Response can be a string, dict, or have various structures
        if isinstance(response, str):
            output = response
        elif isinstance(response, dict):
            # Try different possible keys
            output = (
                response.get("stdout", "")
                or response.get("output", "")
                or response.get("result", "")
                or response.get("stderr", "")
                or str(response.get("content", ""))
            )
        elif hasattr(response, "content"):
            # SDK might wrap response
            output = str(response.content)
        else:
            # Fallback: stringify whatever we got
            output = str(response) if response else ""

        # Normalize to string for safe checks
        if not isinstance(output, str):
            output = str(output)

        if not output or not output.strip():
            return "✓ No output"

        # Filter out SDK-internal permission messages - these are noisy and already handled by our permission handler
        lowered = output.lower()
        if "hook requested permission" in lowered or "permission behavior:" in lowered:
            return None  # Don't show anything - our permission handler already printed the user-friendly message

        lines = output.strip().split("\n")
        line_count = len(lines)

        first_line = lines[0].strip()
        if len(first_line) > cls.MAX_PREVIEW_LENGTH:
            first_line = first_line[: cls.MAX_PREVIEW_LENGTH - 3] + "..."

        if line_count == 1:
            return f"✓ {first_line}"
        return f"✓ {line_count} lines | {first_line}"

    @classmethod
    def _format_mcp_preview(cls, tool_name: str, response: Any) -> str:
        """Format MCP tool result preview as a single line with color indicators."""
        # Extract the actual tool name (remove mcp__ prefix and server name)
        parts = tool_name.split("__")
        clean_name = parts[-1] if len(parts) > 1 else tool_name

        try:
            # Handle different response types
            if isinstance(response, dict):
                # get_system_info - show health status
                if "memory" in response and "load" in response:
                    return cls._format_system_info_preview(response)

                # disk_scan_summary - show disk health
                if "disk" in response or "usage_percent" in response:
                    return cls._format_disk_scan_preview(response)

                # get_directory_sizes - show top directory
                if "directories" in response or "top_directories" in response:
                    return cls._format_directory_sizes_preview(response)

                # find_large_files - show largest file
                if "files" in response or "large_files" in response:
                    return cls._format_large_files_preview(response)

                # get_resource_hogs - show top consumer
                if "top_cpu" in response or "top_memory" in response:
                    return cls._format_resource_hogs_preview(response)

                # find_process_by_name - show match count
                if "processes" in response:
                    procs = response.get("processes", [])
                    count = len(procs) if isinstance(procs, list) else 0
                    return f"✓ {count} matching processes"

                # connection_summary
                if "established" in response or "connections" in response:
                    return cls._format_connection_preview(response)

                # Special handling for process tree
                if "total_processes" in response:
                    total = response["total_processes"]
                    return f"✓ {total} processes"

                # Try to extract meaningful summary
                if "count" in response:
                    return f"✓ {response['count']} items"
                if len(response) == 0:
                    return "✓ Empty result"
                key_count = len(response.keys())
                return f"✓ {key_count} fields"

            if isinstance(response, list):
                count = len(response)
                # Check if it's a list of processes
                if count > 0 and isinstance(response[0], dict) and "pid" in response[0]:
                    return f"✓ {count} processes"
                item_type = clean_name.replace("_", " ").title().rstrip("s")
                plural = "s" if count != 1 else ""
                return f"✓ {count} {item_type.lower()}{plural}"

            if isinstance(response, str):
                # Short string responses
                if len(response) <= cls.MAX_PREVIEW_LENGTH:
                    return f"✓ {response}"
                return f"✓ {response[: cls.MAX_PREVIEW_LENGTH - 3]}..."

            return f"✓ {type(response).__name__}"
        except Exception as e:  # pragma: no cover - defensive
            return f"✓ {e}"

    @classmethod
    def _format_system_info_preview(cls, response: dict) -> str:
        """Format get_system_info with health indicators."""
        mem = response.get("memory", {}) or {}
        load = response.get("load", {}) or {}
        disk = response.get("disk", {}) or {}

        mem_pct = safe_float(mem.get("percent"), 0.0)
        load_1m = safe_float(load.get("1min"), 0.0)
        cpu_count = response.get("cpu_count", 8)

        # Colored severity indicators
        mem_sev = cls._severity(mem_pct, 75, 90)
        load_sev = cls._severity(load_1m, cpu_count, cpu_count * 2)

        parts = [f"mem {mem_pct:.0f}%{mem_sev}", f"load {load_1m:.1f}{load_sev}"]

        # Add disk if available
        if disk:
            disk_pct = safe_float(disk.get("percent"), 0.0)
            disk_sev = cls._severity(disk_pct, 80, 95)
            parts.append(f"disk {disk_pct:.0f}%{disk_sev}")

        return "✓ " + " | ".join(parts)

    @classmethod
    def _format_disk_scan_preview(cls, response: dict) -> str:
        """Format disk_scan_summary with health status."""
        disk = response.get("disk", response)
        pct = safe_float(disk.get("usage_percent", disk.get("percent", 0)), 0.0)
        free_gb = safe_float(disk.get("free_gb", disk.get("free", 0)), 0.0)

        # Colored severity indicator
        sev = cls._severity(pct, 80, 95)

        # Large files count
        large_files = response.get("large_files", [])
        file_count = len(large_files) if isinstance(large_files, list) else 0

        if file_count > 0:
            return f"✓ {pct:.0f}% used{sev} ({free_gb:.1f}GB free) · {file_count} large files"
        return f"✓ {pct:.0f}% used{sev} ({free_gb:.1f}GB free)"

    @classmethod
    def _format_directory_sizes_preview(cls, response: dict) -> str:
        """Format get_directory_sizes showing top directory(s)."""
        # Handle multi-path response
        if "scans" in response and isinstance(response["scans"], list):
            scans = response["scans"]
            total_dirs = 0
            largest_entry = None
            errors = 0
            paths_ok = 0

            for scan in scans:
                if isinstance(scan, dict):
                    # Check for errors/notes (permission issues)
                    if scan.get("error") or scan.get("note"):
                        errors += 1
                    entries = scan.get("entries", [])
                    if entries and isinstance(entries, list):
                        paths_ok += 1
                        total_dirs += len(entries)
                        top = entries[0] if entries else {}
                        if isinstance(top, dict) and (
                            largest_entry is None
                            or top.get("size", "") > largest_entry.get("size", "")
                        ):
                            largest_entry = top

            # Build summary
            parts = []
            if paths_ok > 0:
                parts.append(f"{paths_ok} paths")
            if errors > 0:
                parts.append(f"{errors} denied")
            if total_dirs > 0:
                parts.append(f"{total_dirs} dirs")
            if largest_entry:
                name = str(largest_entry.get("path", "?")).split("/")[-1][:15]
                size = largest_entry.get("size", "?")
                parts.append(f"top: {name} ({size})")

            if not parts:
                return f"✓ {len(scans)} paths (no access)"
            return "✓ " + " | ".join(parts)

        # Single path response
        # Check for error/note first
        if response.get("error"):
            root = str(response.get("root", "?")).split("/")[-1]
            return f"! {root}: access denied"
        if response.get("note"):
            root = str(response.get("root", "?")).split("/")[-1]
            entries = response.get("entries", [])
            if entries:
                size = entries[0].get("size", "?")
                return f"~ {root}: {size} (limited access)"
            return f"~ {root}: limited access"

        # Normal single path - check for "entries" key
        dirs = response.get("entries", response.get("directories", response.get("top_directories", [])))
        if not dirs or not isinstance(dirs, list):
            root = str(response.get("root", "")).split("/")[-1] or "path"
            return f"✓ {root}: empty or no access"

        # Show top directory
        top = dirs[0] if dirs else {}
        if isinstance(top, dict):
            name = top.get("name", top.get("path", "?"))
            size = top.get("size_human", top.get("size", "?"))
            # Truncate long paths - just show directory name
            if "/" in str(name):
                name = str(name).split("/")[-1]
            if len(str(name)) > 20:
                name = str(name)[:17] + "..."
            return f"✓ {len(dirs)} dirs | largest: {name} ({size})"
        return f"✓ {len(dirs)} directories"

    @classmethod
    def _format_large_files_preview(cls, response: dict) -> str:
        """Format find_large_files showing largest file(s)."""
        # Handle multi-path response
        if "scans" in response and isinstance(response["scans"], list):
            scans = response["scans"]
            total_files = 0
            biggest_file = None
            biggest_size = 0
            errors = 0
            paths_ok = 0

            for scan in scans:
                if isinstance(scan, dict):
                    if scan.get("error"):
                        errors += 1
                        continue
                    files = scan.get("files", [])
                    if isinstance(files, list):
                        paths_ok += 1
                        total_files += len(files)
                        for f in files:
                            if isinstance(f, dict):
                                size_mb = safe_float(f.get("size_mb"), 0)
                                if size_mb > biggest_size:
                                    biggest_size = size_mb
                                    biggest_file = f

            # Build summary
            parts = []
            if paths_ok > 0:
                parts.append(f"{paths_ok} paths")
            if errors > 0:
                parts.append(f"{errors} denied")
            if total_files > 0:
                parts.append(f"{total_files} files")
            if biggest_file:
                name = str(biggest_file.get("path", "?")).split("/")[-1][:18]
                parts.append(f"biggest: {name}")

            if not parts:
                return f"✓ {len(scans)} paths (no access)"
            return "✓ " + " | ".join(parts)

        # Single path response - check for error first
        if response.get("error"):
            root = str(response.get("root", "?")).split("/")[-1]
            return f"! {root}: access denied"

        files = response.get("files", response.get("large_files", []))
        if not files or not isinstance(files, list):
            return "✓ No large files found"

        count = len(files)
        top = files[0] if files else {}
        if isinstance(top, dict):
            name = top.get("name", top.get("path", "?"))
            size = top.get("size_human", top.get("size", "?"))
            # Just show filename, not full path
            if "/" in str(name):
                name = str(name).split("/")[-1]
            if len(str(name)) > 25:
                name = str(name)[:22] + "..."
            return f"✓ {count} large files | biggest: {name} ({size})"
        return f"✓ {count} large files"

    @classmethod
    def _format_resource_hogs_preview(cls, response: dict) -> str:
        """Format get_resource_hogs showing top consumers."""
        top_cpu = response.get("top_cpu", [])
        top_mem = response.get("top_memory", [])

        parts = []

        # Top CPU consumer
        if top_cpu and isinstance(top_cpu, list) and len(top_cpu) > 0:
            proc = top_cpu[0]
            if isinstance(proc, dict):
                name = proc.get("name", "?")[:15]
                cpu = safe_float(proc.get("cpu_percent"), 0.0)
                cpu_sev = cls._severity(cpu, 25, 50)
                parts.append(f"CPU: {name} {cpu:.0f}%{cpu_sev}")

        # Top memory consumer
        if top_mem and isinstance(top_mem, list) and len(top_mem) > 0:
            proc = top_mem[0]
            if isinstance(proc, dict):
                name = proc.get("name", "?")[:15]
                mem_mb = safe_float(proc.get("memory_mb", proc.get("rss_mb", 0)), 0.0)
                mem_sev = cls._severity(mem_mb, 500, 1000)
                parts.append(f"Mem: {name} {mem_mb:.0f}MB{mem_sev}")

        if parts:
            return "✓ " + " | ".join(parts)
        return "✓ Resource data collected"

    @classmethod
    def _format_connection_preview(cls, response: dict) -> str:
        """Format connection_summary."""
        established = response.get("established", 0)
        listening = response.get("listening", 0)
        return f"✓ {established} connections, {listening} listening"

    @classmethod
    def _format_network_preview(cls, tool_name: str, response: Any) -> str:
        """Format network tool result preview."""
        if isinstance(response, dict):
            # WebFetch might have status_code and content
            status = response.get("status_code", "")
            content = response.get("content", "") or response.get("result", "")

            if status:
                # Calculate size
                size = len(str(content)) if content else 0
                size_str = cls._format_bytes(size)
                return f"✓ {status} ({size_str})"

        # WebSearch results
        if isinstance(response, list):
            return f"✓ {len(response)} results"

        return "✓ Response received"

    @classmethod
    def _format_skill_preview(cls, response: Any) -> str:
        """Format Skill tool invocation preview."""
        if isinstance(response, dict):
            skill_name = response.get("skill_name", response.get("name", "unknown"))
            return f"✓ Launching skill: {skill_name}"
        if isinstance(response, str):
            # Try to extract skill name from response text
            if "skill" in response.lower():
                # Look for skill name pattern
                lines = response.split("\n")
                for line in lines[:5]:
                    if "running" in line.lower() or "skill" in line.lower():
                        return f"✓ {line.strip()[:60]}"
            return "✓ Skill activated"
        return "✓ Skill invoked"

    @classmethod
    def _format_default_preview(cls, response: Any) -> str:
        """Format generic response preview."""
        if isinstance(response, list | tuple):
            return f"✓ {len(response)} items"

        elif isinstance(response, dict):
            if not response:
                return "✓ Empty result"
            return f"✓ {len(response)} fields"

        elif isinstance(response, str):
            if not response:
                return "✓ Empty string"
            lines = response.split("\n")
            if len(lines) > 1:
                return f"✓ {len(lines)} lines"
            elif len(response) <= cls.MAX_PREVIEW_LENGTH:
                return f"✓ {response}"
            else:
                return f"✓ {response[:cls.MAX_PREVIEW_LENGTH - 3]}..."

        elif isinstance(response, int | float):
            return f"✓ {response}"

        elif response is None:
            return "✓ No result"

        return f"✓ {type(response).__name__}"

    @classmethod
    def _format_bytes(cls, size: int) -> str:
        """Format byte size in human-readable format."""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"
