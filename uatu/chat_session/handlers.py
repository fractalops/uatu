"""Message and streaming response handlers."""

import asyncio
import contextlib
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ResultMessage
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from uatu.chat_session.stats import SessionStats
from uatu.config import get_settings
from uatu.telemetry import NoopTelemetry, TelemetryEmitter, hash_with_salt, summarize_command
from uatu.tools.constants import Tools
from uatu.ui.console import ConsoleRenderer


@dataclass
class TurnTelemetry:
    """Lightweight per-turn tracking to keep MessageHandler lean."""

    start_ts: float | None = None
    tool_count: int = 0
    last_text_tool_count: int = 0
    background_poll_count: int = 0
    background_label: str | None = None
    background_start_ts: float | None = None  # When background job started
    # Track multiple running tools: tool_use_id -> (name, start_ts)
    running_tools: dict = None  # type: ignore  # Will be dict[str, tuple[str, float]]
    # Phase tracking for spinner display
    phase: str = "thinking"  # thinking, gathering, analyzing, summarizing

    def __post_init__(self):
        if self.running_tools is None:
            self.running_tools = {}

    def start(self) -> None:
        self.start_ts = time.monotonic()
        self.tool_count = 0
        self.last_text_tool_count = 0
        self.background_poll_count = 0
        self.background_label = None
        self.background_start_ts = None
        self.running_tools = {}
        self.phase = "thinking"

    def update_phase(self) -> str:
        """Determine current phase based on activity."""
        if self.tool_count == 0:
            self.phase = "thinking"
        elif self.running_tools:
            self.phase = "gathering"
        elif self.tool_count > 0 and self.last_text_tool_count < self.tool_count:
            self.phase = "analyzing"
        else:
            self.phase = "summarizing"
        return self.phase

    def record_tool(self, tool_name: str) -> None:
        self.tool_count += 1

    def record_text(self) -> None:
        self.last_text_tool_count = self.tool_count

    def record_background_poll(self) -> None:
        self.background_poll_count += 1

    def start_tool(self, tool_id: str, tool_name: str) -> None:
        """Start tracking a tool execution.

        Args:
            tool_id: Unique tool_use_id from the SDK
            tool_name: Human-readable tool name
        """
        self.running_tools[tool_id] = (tool_name, time.monotonic())

    def stop_tool(self, tool_id: str | None = None) -> float:
        """Stop tracking a tool, return elapsed time.

        Args:
            tool_id: Tool to stop. If None, stops the oldest tool.
        """
        if not self.running_tools:
            return 0.0

        if tool_id and tool_id in self.running_tools:
            name, start_ts = self.running_tools.pop(tool_id)
            return time.monotonic() - start_ts

        # Fallback: stop oldest tool if no ID provided
        if self.running_tools:
            oldest_id = next(iter(self.running_tools))
            name, start_ts = self.running_tools.pop(oldest_id)
            return time.monotonic() - start_ts

        return 0.0

    def running_tools_count(self) -> int:
        """Get count of currently running tools."""
        return len(self.running_tools)

    def running_tools_summary(self) -> str:
        """Get summary of running tools for spinner display."""
        if not self.running_tools:
            return ""

        count = len(self.running_tools)
        if count == 1:
            # Single tool: show name and elapsed time
            tool_id, (name, start_ts) = next(iter(self.running_tools.items()))
            elapsed = time.monotonic() - start_ts
            return f"{name} ({elapsed:.1f}s)"
        else:
            # Multiple tools: show count and max elapsed
            max_elapsed = max(time.monotonic() - ts for _, ts in self.running_tools.values())
            return f"{count} tools running ({max_elapsed:.1f}s)"

    # Legacy compatibility
    @property
    def current_tool_name(self) -> str | None:
        """Legacy: return first running tool name."""
        if self.running_tools:
            return next(iter(self.running_tools.values()))[0]
        return None

    def tool_elapsed(self) -> float:
        """Get max elapsed time across all running tools."""
        if not self.running_tools:
            return 0.0
        return max(time.monotonic() - ts for _, ts in self.running_tools.values())

    def start_background(self, label: str) -> None:
        """Start tracking a background job."""
        self.background_label = label
        self.background_start_ts = time.monotonic()

    def stop_background(self) -> float:
        """Stop tracking background job, return elapsed time."""
        elapsed = 0.0
        if self.background_start_ts:
            elapsed = time.monotonic() - self.background_start_ts
        self.background_label = None
        self.background_start_ts = None
        return elapsed

    def background_elapsed(self) -> float:
        """Get elapsed time for current background job."""
        if self.background_start_ts:
            return time.monotonic() - self.background_start_ts
        return 0.0

    def reset_after_summary(self) -> None:
        self.tool_count = 0
        self.last_text_tool_count = 0
        self.background_poll_count = 0
        self.background_label = None
        self.background_start_ts = None
        self.running_tools = {}
        self.phase = "thinking"


@dataclass
class BackgroundJob:
    """Tracks a background Bash job."""

    shell_id: str | None
    command: str
    start_time: float
    status: str = "running"  # running, completed, failed, killed
    exit_code: int | None = None
    label: str | None = None

    @classmethod
    def from_tool_input(cls, tool_input: dict[str, Any]) -> "BackgroundJob":
        """Create a BackgroundJob from Bash tool input."""
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        label = command.split("\n", 1)[0][:40] if command else "background"
        if len(label) < len(command.split("\n", 1)[0]):
            label += "..."
        return cls(
            shell_id=None,  # Will be set when result arrives
            command=command,
            start_time=time.monotonic(),
            label=label,
        )

    @property
    def elapsed_seconds(self) -> float:
        """Time elapsed since job started."""
        return time.monotonic() - self.start_time

    def mark_completed(self, exit_code: int | None = None) -> None:
        """Mark job as completed."""
        self.status = "completed"
        self.exit_code = exit_code

    def mark_failed(self, exit_code: int | None = None) -> None:
        """Mark job as failed."""
        self.status = "failed"
        self.exit_code = exit_code


class MessageHandler:
    """Handles message streaming and display."""

    def __init__(
        self,
        console: Console,
        telemetry: TelemetryEmitter | NoopTelemetry,
        session_id: str,
        session_salt: str,
        settings=None,
    ):
        """Initialize message handler.

        Args:
            console: Rich console for output
            telemetry: Telemetry emitter (noop when disabled)
            session_id: Unique session identifier
            settings: Optional preloaded settings
        """
        self.console = console
        self.renderer = ConsoleRenderer(console)
        self.settings = settings or get_settings()
        self.telemetry_emitter = telemetry
        self.session_id = session_id
        self.session_salt = session_salt
        # Map tool_use_id to tool_name for matching results to tools
        self.tool_use_map: dict[str, str] = {}
        # Track session statistics
        self.stats = SessionStats()
        self.stats.max_budget_usd = self.settings.uatu_max_budget_usd
        # Live turn state
        self.turn_state = TurnTelemetry()
        # Track per-tool timing
        self.tool_start_ts: dict[str, float] = {}
        self.tool_meta: dict[str, dict[str, Any]] = {}
        # Background Bash job tracking - supports multiple concurrent jobs
        self.running_background_jobs: dict[str, BackgroundJob] = {}  # shell_id -> job
        self.background_job_queue: list[BackgroundJob] = []
        self.turn_seen_basics: set[str] = set()
        # Optional prompt refresher (set by ChatSession)
        self.refresh_prompt: callable | None = None
        # Keep last assistant text for recovery
        self.last_summary: str | None = None
        # Keep last user request for recovery
        self.last_user_input: str | None = None
        # Rolling session summary
        self.rolling_summary: str | None = None
        # Serialize message handling to avoid concurrent tool calls
        self._message_lock = asyncio.Lock()
        # Track tool usage and previews for fallback summaries
        self.tool_usage_log: list[str] = []
        self.tool_result_previews: dict[str, str] = {}
        # Force wrap-up guard (from settings)
        self.max_tools_per_turn: int = self.settings.uatu_max_tools_per_turn
        self.max_tools_per_turn_bg: int = self.settings.uatu_max_tools_per_turn_bg
        self.max_elapsed_seconds: float = self.settings.uatu_max_elapsed_seconds
        # Background polling limit for BashOutput
        self.max_bg_polls: int = self.settings.uatu_max_bg_polls
        self.max_background_jobs: int = (
            self.settings.uatu_max_background_jobs
            if hasattr(self.settings, "uatu_max_background_jobs")
            else 1
        )
        self.background_queue_size: int = (
            self.settings.uatu_background_queue_size if hasattr(self.settings, "uatu_background_queue_size") else 1
        )
        # Telemetry counters per turn
        self.turn_bash_tools: int = 0
        self.turn_mcp_tools: int = 0
        self.turn_bash_disk_tools: int = 0
        self.turn_skill_invocations: int = 0
        self.bg_soft_denies: int = 0
        self.bg_hard_denies: int = 0
        self.last_tool_end_ts: float | None = None

    def _print_stats_line(self) -> None:
        """Print a lightweight inline stats line if enabled."""
        if (
            self.settings.uatu_show_stats
            and self.stats.conversation_turns > 0
            and sys.stdout.isatty()
        ):
            self.console.print(f"[dim cyan]{self.stats.format_compact()}[/dim cyan]")

    async def _refresh_loop(
        self,
        stop_event: asyncio.Event,
        interval: float = 0.5,
        spinner_obj: Spinner | None = None,
        telemetry: TurnTelemetry | None = None,
    ) -> None:
        """Periodically refresh prompt/spinner to show live stats."""
        while not stop_event.is_set():
            if spinner_obj:
                elapsed = 0.0
                if telemetry and telemetry.start_ts is not None:
                    elapsed = time.monotonic() - telemetry.start_ts

                # Update and get current phase
                phase = telemetry.update_phase() if telemetry else "thinking"
                phase_display = {
                    "thinking": "Pondering",
                    "gathering": "Gathering",
                    "analyzing": "Analyzing",
                    "summarizing": "Summarizing",
                }
                phase_text = phase_display.get(phase, "Pondering")

                # Build spinner text with phase
                spinner_text = Text(f"{phase_text}... ", style="cyan")
                spinner_text.append(f"{elapsed:0.1f}s", style="dim")
                if telemetry and telemetry.tool_count > 0:
                    spinner_text.append(f" · {telemetry.tool_count} tools", style="dim")

                # Show running tools with live elapsed time
                if telemetry and telemetry.running_tools_count() > 0:
                    summary = telemetry.running_tools_summary()
                    spinner_text.append("\n", style="dim")
                    spinner_text.append("  ↳ ", style="dim")
                    spinner_text.append(summary, style="dim cyan")

                # Show background job on new line
                if telemetry and telemetry.background_label:
                    bg_elapsed = telemetry.background_elapsed()
                    spinner_text.append("\n", style="dim")
                    spinner_text.append("  ↳ bg: ", style="dim green")
                    label = telemetry.background_label[:40]
                    spinner_text.append(f"{label}", style="dim")
                    spinner_text.append(f" ({bg_elapsed:.0f}s)", style="dim yellow")

                # Budget remaining (if tracking)
                if self.settings.uatu_show_stats:
                    if self.stats.max_budget_usd and self.stats.total_cost_usd:
                        remaining = max(self.stats.max_budget_usd - self.stats.total_cost_usd, 0)
                        spinner_text.append(f" · ${remaining:.4f}", style="dim")

                spinner_obj.text = spinner_text
            if self.refresh_prompt:
                try:
                    self.refresh_prompt()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                continue

    def _emit_turn_event(
        self,
        turn_id: str,
        phase: str,
        status: str = "ok",
        elapsed_ms: float | None = None,
        tool_count: int | None = None,
        user_input_len: int | None = None,
        prompt_hash: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "event_type": "turn",
            "phase": phase,
            "session_id": self.session_id,
            "turn_id": turn_id,
            "status": status,
        }
        if elapsed_ms is not None:
            event["elapsed_ms"] = elapsed_ms
        if tool_count is not None:
            event["tool_count"] = tool_count
        if user_input_len is not None:
            event["user_input_len"] = user_input_len
        if prompt_hash:
            event["prompt_hash"] = prompt_hash
        event["settings"] = {
            "read_only": self.settings.uatu_read_only,
            "allow_network": self.settings.uatu_allow_network,
            "tools_mode": self.settings.uatu_tools_mode,
            "require_approval": getattr(self.settings, "uatu_require_approval", True),
        }
        if extra:
            event.update(extra)
        self.telemetry_emitter.emit(event)

    def _emit_summary_event(self, turn_id: str, source: str, summary_text: str | None) -> None:
        """Emit a summary telemetry event with minimal payload."""
        if not summary_text:
            return
        preview = summary_text[:500]
        latency_ms_since_last_tool = None
        latency_ms_since_turn_start = None
        now = time.monotonic()
        if self.last_tool_end_ts:
            latency_ms_since_last_tool = (now - self.last_tool_end_ts) * 1000
        if self.turn_state.start_ts:
            latency_ms_since_turn_start = (now - self.turn_state.start_ts) * 1000
        event = {
            "event_type": "summary",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "source": source,
            "summary_len": len(summary_text),
            "summary_preview": preview,
        }
        if latency_ms_since_last_tool is not None:
            event["latency_ms_since_last_tool"] = latency_ms_since_last_tool
        if latency_ms_since_turn_start is not None:
            event["latency_ms_since_turn_start"] = latency_ms_since_turn_start
        self.telemetry_emitter.emit(event)

    def _emit_tool_start(
        self,
        turn_id: str,
        tool_use_id: str | None,
        tool_name: str,
        tool_input: dict[str, Any] | None,
    ) -> None:
        meta: dict[str, Any] = {"tool": tool_name, "turn_id": turn_id}
        if tool_input:
            if tool_name == Tools.BASH:
                meta.update(summarize_command(tool_input.get("command", "")))
                meta["run_in_background"] = bool(
                    tool_input.get("run_in_background") or tool_input.get("background")
                )
            elif tool_name.startswith("mcp__"):
                meta["params_keys"] = list(tool_input.keys())[:5]
        # Count tool mix for telemetry
        if tool_name == Tools.BASH:
            self.turn_bash_tools += 1
            cmd = ""
            if isinstance(tool_input, dict):
                cmd = str(tool_input.get("command", "")).lower()
            if "du " in cmd or "find " in cmd:
                self.turn_bash_disk_tools += 1
        elif tool_name.startswith("mcp__"):
            self.turn_mcp_tools += 1
        elif tool_name == "Skill":
            self.turn_skill_invocations += 1
        self.telemetry_emitter.emit(
            {
                "event_type": "tool_call",
                "phase": "start",
                "session_id": self.session_id,
                "turn_id": turn_id,
                "tool": tool_name,
                **meta,
            }
        )
        if tool_use_id:
            self.tool_meta[tool_use_id] = meta

    def _emit_tool_end(
        self,
        turn_id: str,
        tool_use_id: str | None,
        tool_name: str,
        start_ts: float | None,
        status: str,
    ) -> None:
        duration_ms = None
        now = time.monotonic()
        if start_ts:
            duration_ms = (now - start_ts) * 1000
        self.last_tool_end_ts = now
        base_meta = self.tool_meta.pop(tool_use_id, {}) if tool_use_id else {}
        event = {
            "event_type": "tool_call",
            "phase": "end",
            "session_id": self.session_id,
            "turn_id": turn_id,
            "tool": tool_name,
            "status": status,
            **base_meta,
        }
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        self.telemetry_emitter.emit(event)

    def reset_stats(self) -> None:
        """Reset session statistics (called when context is cleared)."""
        self.stats.reset()
        self.tool_usage_log.clear()
        self.tool_result_previews.clear()
        self.last_summary = None
        self.rolling_summary = None
        self.turn_state = TurnTelemetry()
        self.running_background_jobs = {}
        self.background_job_queue = []
        self.turn_seen_basics = set()

    def _handle_text_block(
        self,
        block: Any,
        response_text: str,
        spinner: Any,
    ) -> tuple[str, bool]:
        """Handle a text content block.

        Args:
            block: Text block from Claude
            response_text: Accumulated response text
            spinner: Live spinner widget (may be None)

        Returns:
            Tuple of (updated response_text, True if text was processed)
        """
        if spinner and spinner.is_started:
            spinner.stop()
            # Print header when we start getting text
            if not response_text:
                self.console.print()
                self.console.print("[bold cyan]Uatu:[/bold cyan]")
                self.console.print()

        # Render each text block, preferring structured layout
        self.renderer.show_text(block.text)
        response_text += block.text
        self.turn_state.record_text()
        return response_text, True

    def _should_deny_tool_for_background(self, tool_name: str) -> bool:
        """Check if a tool should be denied due to background job running.

        Strategy:
        - Always allow BashOutput (polling background jobs)
        - Always allow MCP tools (no I/O contention with background Bash)
        - Allow Read/Write/other non-Bash tools
        - Only soft-deny additional Bash commands to prevent I/O contention

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool should be denied
        """
        if not self.running_background_jobs:
            return False

        # Always allow polling background jobs
        if tool_name == Tools.BASH_OUTPUT:
            return False

        # Allow MCP tools - they don't compete for disk I/O
        if tool_name.startswith("mcp__"):
            return False

        # Allow non-Bash SDK tools (Read, Write, etc.)
        if tool_name != Tools.BASH:
            return False

        # Additional Bash commands - check if we're at capacity
        # If we have room for more concurrent jobs, don't deny
        if len(self.running_background_jobs) < self.max_background_jobs:
            return False

        # At max concurrent jobs - soft deny new Bash to avoid I/O contention
        if self.bg_soft_denies == 0:
            self.bg_soft_denies += 1
            count = len(self.running_background_jobs)
            self.console.print(f"[dim yellow]  ↳ {count} background job(s) running, queuing...[/dim yellow]")
        else:
            self.bg_hard_denies += 1
        return True

    def _track_background_job(self, tool_name: str, tool_input: dict[str, Any] | None) -> bool:
        """Track and manage background Bash jobs.

        Supports multiple concurrent background jobs up to max_background_jobs.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters

        Returns:
            True if the tool should be skipped (at max capacity)
        """
        if (
            tool_name != Tools.BASH
            or not isinstance(tool_input, dict)
            or not tool_input.get("run_in_background")
        ):
            return False

        # Create the job
        bg_job = BackgroundJob.from_tool_input(tool_input)

        # Check if we're at max concurrent jobs
        running_count = len(self.running_background_jobs)
        if running_count >= self.max_background_jobs:
            # Check if we can queue this job
            if len(self.background_job_queue) >= self.background_queue_size:
                self.console.print(
                    f"[dim yellow]  ! Max background jobs ({self.max_background_jobs} running, "
                    f"{len(self.background_job_queue)} queued)[/dim yellow]"
                )
                return True

            # Queue the job
            self.background_job_queue.append(bg_job)
            label = (bg_job.label or "job")[:25]
            self.console.print(f"[dim cyan]  ~ Queued: {label}[/dim cyan]")
            return False  # Don't skip - let SDK handle it

        # We can run this job concurrently
        # Note: We'll assign the shell_id when we get the tool result
        # For now, track with a placeholder
        placeholder_id = f"pending_{len(self.running_background_jobs)}"
        self.running_background_jobs[placeholder_id] = bg_job

        # Update spinner to show background count
        job_labels = [j.label or "bg" for j in self.running_background_jobs.values()]
        self.turn_state.start_background(", ".join(job_labels)[:40])

        if running_count > 0:
            label = bg_job.label or "job"
            self.console.print(f"[dim green]  + Background #{running_count + 1}: {label}[/dim green]")

        return False

    def _handle_tool_result(
        self,
        tool_use_id: str,
        tool_response: Any,
        turn_id: str,
    ) -> None:
        """Handle a tool result block.

        Args:
            tool_use_id: ID of the tool use
            tool_response: Response content from the tool
            turn_id: Current turn ID
        """
        # Look up the tool name from our tracking map
        tool_name = self.tool_use_map.get(tool_use_id, "unknown")

        # Stop tracking this specific tool for spinner
        self.turn_state.stop_tool(tool_use_id)

        # Timing: show elapsed if we tracked start
        elapsed_msg = ""
        start_ts = self.tool_start_ts.pop(tool_use_id, None)
        if start_ts:
            elapsed = time.monotonic() - start_ts
            elapsed_msg = f" [{elapsed:0.1f}s]"

        # Show tool result preview if enabled
        if self.settings.uatu_show_tool_previews:
            preview_str = self.renderer.show_tool_result(tool_name, tool_response)
            if preview_str:
                self.tool_result_previews[tool_use_id] = preview_str
            if elapsed_msg:
                pretty_name = self.renderer.clean_tool_name(tool_name)
                msg = f"{pretty_name} finished{elapsed_msg}"
                self.renderer.status(msg, status="info", dim=True)

        status_label = "ok"
        if tool_response and "error" in str(tool_response).lower():
            status_label = "error"

        self._emit_tool_end(
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            start_ts=start_ts,
            status=status_label,
        )

        # Track shell_id when Bash background command starts
        if tool_name == Tools.BASH and isinstance(tool_response, dict):
            shell_id = tool_response.get("shellId")
            if shell_id:
                # Find a pending job and assign the shell_id
                for pending_id in list(self.running_background_jobs.keys()):
                    if pending_id.startswith("pending_"):
                        job = self.running_background_jobs.pop(pending_id)
                        job.shell_id = shell_id
                        self.running_background_jobs[shell_id] = job
                        break

        # Handle BashOutput result - check if a job completed
        if tool_name == Tools.BASH_OUTPUT:
            self.turn_state.record_background_poll()
            # Check response status
            is_completed = False
            if isinstance(tool_response, dict):
                status = tool_response.get("status", "")
                is_completed = status in ("completed", "failed")
            elif isinstance(tool_response, str):
                is_completed = "completed" in tool_response.lower() or "exit" in tool_response.lower()

            if is_completed and self.running_background_jobs:
                # Remove one completed job (we don't always know which one)
                if self.running_background_jobs:
                    completed_id = next(iter(self.running_background_jobs))
                    completed_job = self.running_background_jobs.pop(completed_id)
                    completed_job.mark_completed()

                    # Update spinner with remaining jobs
                    if self.running_background_jobs:
                        remaining = [j.label or "bg" for j in self.running_background_jobs.values()]
                        self.turn_state.background_label = ", ".join(remaining)[:40]
                        still = len(self.running_background_jobs)
                        self.console.print(f"[dim green]  ✓ Job done, {still} running[/dim green]")
                    else:
                        bg_elapsed = self.turn_state.stop_background()
                        self.console.print(f"[dim green]  ✓ All background jobs done ({bg_elapsed:.1f}s)[/dim green]")

                # Start next queued job if we have capacity
                while (
                    self.background_job_queue
                    and len(self.running_background_jobs) < self.max_background_jobs
                ):
                    next_job = self.background_job_queue.pop(0)
                    placeholder = f"pending_{len(self.running_background_jobs)}"
                    self.running_background_jobs[placeholder] = next_job
                    label = (next_job.label or "job")[:30]
                    self.console.print(f"[dim cyan]  -> Starting queued: {label}[/dim cyan]")

    def _build_fallback_summary(self) -> str:
        """Build a fallback summary from tool activity when model returns no text.

        Returns:
            Fallback summary string
        """
        fallback_lines: list[str] = []
        if self.tool_usage_log:
            tools_str = ", ".join(self.tool_usage_log[-8:])
            fallback_lines.append(f"Tools executed: {tools_str}")
        if self.tool_result_previews:
            fallback_lines.append("Top results:")
            for _, preview in list(self.tool_result_previews.items())[-8:]:
                fallback_lines.append(f"- {preview}")
        return "\n".join(fallback_lines) if fallback_lines else "No assistant summary returned."

    async def _auto_summary_turn(
        self,
        client: ClaudeSDKClient,
        summary_prompt: str,
        parent_turn_id: str,
    ) -> None:
        """Auto-prompt the model for a summary when a turn ends without one.

        This is a lightweight turn that just asks for text summary, no tools.

        Args:
            client: Claude SDK client
            summary_prompt: The prompt asking for summary
            parent_turn_id: The turn ID that triggered this auto-summary
        """
        summary_text = ""

        # Send the summary request first, then receive messages
        await client.query(summary_prompt)

        # Receive the response
        async for message in client.receive_messages():
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        # Stream text as it arrives
                        if not summary_text:
                            self.console.print()  # Add spacing before summary
                        summary_text += block.text

            # Check for ResultMessage (turn complete)
            if isinstance(message, ResultMessage):
                # Also check if ResultMessage has a result field
                if hasattr(message, "result") and message.result:
                    summary_text = message.result
                break

        # Display the summary
        if summary_text.strip():
            self.renderer.show_text(summary_text.strip())
            self.last_summary = summary_text.strip()
            if self.rolling_summary:
                self.rolling_summary = f"{self.rolling_summary}\n\n{summary_text.strip()}"
            else:
                self.rolling_summary = summary_text.strip()
            self._emit_summary_event(parent_turn_id, "auto_summary", summary_text.strip())
            self.console.print()
        else:
            # No text returned even from summary request
            self.console.print("[dim yellow]  ! No summary available[/dim yellow]")

    async def handle_message(self, client: ClaudeSDKClient, user_message: str) -> None:
        """Handle a user message and stream response.

        Uses receive_messages() instead of receive_response() to capture ALL
        tool results (including Bash) via ToolResultBlock in the message stream.
        PostToolUse hooks only fire for MCP tools, so we capture results here.

        Args:
            client: Claude SDK client
            user_message: User's message
        """
        self.last_user_input = user_message
        attempts = 2
        async with self._message_lock:
            turn_id = str(uuid.uuid4())
            turn_status = "in_progress"
            prompt_hash = hash_with_salt(self.session_salt, user_message)
            self._emit_turn_event(
                turn_id=turn_id,
                phase="start",
                status=turn_status,
                user_input_len=len(user_message or ""),
                prompt_hash=prompt_hash,
            extra={
                "bash_tools": 0,
                "mcp_tools": 0,
                "bash_disk_tools": 0,
                "skill_invocations": 0,
            },
            )
            for attempt in range(1, attempts + 1):
                turn_completed = False
                # Per-turn tracking
                self.tool_usage_log.clear()
                self.tool_result_previews.clear()
                self.turn_state = TurnTelemetry()
                self.turn_seen_basics = set()
                self.turn_bash_tools = 0
                self.turn_mcp_tools = 0
                self.turn_bash_disk_tools = 0
                self.turn_skill_invocations = 0
                self.bg_soft_denies = 0
                self.bg_hard_denies = 0
                self.last_tool_end_ts = None
                response_text = ""
                spinner = None
                live: Live | None = None
                spinner_obj: Spinner | None = None
                has_tty_output = sys.stdout.isatty()
                stop_event: asyncio.Event | None = None
                tick_task: asyncio.Task | None = None
                # ESC interrupt removed to avoid interfering with approvals

                try:
                    # Show progress indicator - spinner for TTY output, simple message otherwise
                    self.turn_state.start()
                    if has_tty_output:
                        stats_line = self.stats.format_compact() if self.settings.uatu_show_stats else ""
                        spinner_text = Text("Pondering... ", style="cyan")
                        if stats_line:
                            spinner_text.append(stats_line, style="dim")
                        spinner_obj = Spinner("dots", text=spinner_text)
                        live = Live(
                            spinner_obj,
                            console=self.renderer.console,
                            refresh_per_second=12,
                            transient=True,
                        )
                        live.start()
                        spinner = live
                        # Periodically refresh rprompt stats while thinking
                        stop_event = asyncio.Event()
                        tick_task = asyncio.create_task(
                            self._refresh_loop(stop_event, spinner_obj=spinner_obj, telemetry=self.turn_state)
                        )
                    else:
                        # When output is piped/redirected, show a simple status message
                        self.console.print("[dim cyan]→ Processing...[/dim cyan]")

                    # Send query (context maintained automatically)
                    await client.query(user_message)

                    # Start escape listener to allow mid-turn interrupt (ESC key)
                    # ESC interrupt disabled intentionally

                    # Receive and process ALL messages (including tool results)
                    result_msg = None
                    turn_start = self.turn_state.start_ts or time.monotonic()
                    async for message in client.receive_messages():
                        if turn_completed:
                            break
                        # No ESC interrupt path

                        # Turn guards: too many tools or too long without text -> ask model to summarize
                        elapsed = time.monotonic() - turn_start
                        has_bg_job = len(self.running_background_jobs) > 0
                        tool_cap = self.max_tools_per_turn_bg if has_bg_job else self.max_tools_per_turn
                        if (
                            self.turn_state.tool_count >= tool_cap
                            or elapsed >= self.max_elapsed_seconds
                        ) and not response_text:
                            self.renderer.status(
                                "Wrapping up...",
                                status="info",
                                dim=True,
                            )
                            with contextlib.suppress(Exception):
                                await client.interrupt()
                            turn_status = "wrap_up"
                            turn_completed = True
                            break

                        # Check for ResultMessage to know when to stop
                        if isinstance(message, ResultMessage):
                            result_msg = message
                            break

                        message_has_text = False
                        message_has_tools = False

                        if hasattr(message, "content"):
                            for block in message.content:
                                # Text content
                                if hasattr(block, "text"):
                                    response_text, message_has_text = self._handle_text_block(
                                        block, response_text, spinner
                                    )

                                # Tool usage (when Claude calls a tool)
                                elif hasattr(block, "name") and hasattr(block, "input"):
                                    if spinner and spinner.is_started:
                                        spinner.stop()

                                    message_has_tools = True
                                    tool_name = block.name
                                    tool_input = block.input if hasattr(block, "input") else None

                                    # Check if background job should block this tool
                                    if self._should_deny_tool_for_background(tool_name):
                                        continue

                                    # Track basic disk tools for telemetry (dedup is handled by hook)
                                    basic_tools = {
                                        Tools.DISK_SCAN_SUMMARY,
                                        Tools.GET_DIRECTORY_SIZES,
                                        Tools.FIND_LARGE_FILES,
                                        "mcp__safe-hints__disk_usage_summary",
                                    }
                                    if tool_name in basic_tools:
                                        self.turn_seen_basics.add(tool_name)

                                    # Update telemetry
                                    self.turn_state.record_tool(tool_name)
                                    start_ts = time.monotonic()
                                    self.tool_usage_log.append(self.renderer.clean_tool_name(tool_name))
                                    tool_use_id = getattr(block, "id", None)

                                    # Track background Bash job
                                    if self._track_background_job(tool_name, tool_input):
                                        continue
                                    self._emit_tool_start(
                                        turn_id=turn_id,
                                        tool_use_id=tool_use_id,
                                        tool_name=tool_name,
                                        tool_input=tool_input,
                                    )
                                    # Track tool_use_id for matching results later
                                    if tool_use_id:
                                        self.tool_use_map[tool_use_id] = tool_name
                                        self.tool_start_ts[tool_use_id] = start_ts

                                    # Track current tool for spinner display
                                    clean_name = self.renderer.clean_tool_name(tool_name)
                                    if tool_use_id:
                                        self.turn_state.start_tool(tool_use_id, clean_name)

                                    # Show tool usage with enhanced display
                                    self.renderer.show_tool_usage(tool_name, tool_input)

                                # Tool result (when tool execution completes)
                                # These come in UserMessage blocks via receive_messages()
                                elif hasattr(block, "tool_use_id") and hasattr(block, "content"):
                                    self._handle_tool_result(
                                        tool_use_id=block.tool_use_id,
                                        tool_response=block.content,
                                        turn_id=turn_id,
                                    )

                        # Restart spinner after tools (waiting for next response)
                        if message_has_tools and not message_has_text:
                            self.console.print()  # Breathing room
                            if spinner and not spinner.is_started:
                                spinner.start()

                        # Background poll guard: if too many BashOutput "running" polls, stop and summarize
                        if (
                            isinstance(message, ResultMessage) is False
                            and self.turn_state.background_poll_count >= self.max_bg_polls
                        ):
                            with contextlib.suppress(Exception):
                                await client.interrupt()
                            turn_status = "wrap_up"
                            turn_completed = True
                            self.renderer.status(
                                "Background still running; proceeding.",
                                status="info",
                                dim=True,
                            )
                            break

                    # If no ResultMessage arrived (e.g., aborted/timeout), auto-prompt for summary
                    if not result_msg:
                        self.console.print("[dim cyan]  → Auto-summarizing...[/dim cyan]")
                        # Clear background state before auto-summary
                        if self.turn_state.background_label:
                            self.turn_state.stop_background()
                        self.running_background_jobs.clear()
                        self.background_job_queue.clear()

                        # Auto-prompt for summary - recursive call with summary request
                        summary_prompt = (
                            "Please provide a brief summary of your findings so far. "
                            "Focus on key results and any issues discovered. "
                            "Do not run any more tools - just summarize what you found."
                        )
                        try:
                            await self._auto_summary_turn(client, summary_prompt, turn_id)
                            turn_status = "auto_summary"
                            turn_completed = True
                            return
                        except Exception:
                            # If auto-summary fails, fall back to synthetic summary
                            self.console.print("[dim yellow]  ! Summary unavailable[/dim yellow]")
                            fallback_lines: list[str] = ["---", "**Activity Summary**:"]
                            if self.tool_usage_log:
                                recent = self.tool_usage_log[-6:]
                                fallback_lines.append(f"• Ran {len(self.tool_usage_log)} tools: {', '.join(recent)}")
                            if self.tool_result_previews:
                                fallback_lines.append("• Key results:")
                                for _, preview in list(self.tool_result_previews.items())[-4:]:
                                    clean_preview = preview.replace("✓ ", "").strip()[:80]
                                    if clean_preview:
                                        fallback_lines.append(f"  - {clean_preview}")
                            fallback_text = "\n".join(fallback_lines)
                            self.renderer.show_text(fallback_text)
                            self.last_summary = fallback_text
                            self._emit_summary_event(turn_id, "fallback_no_result", fallback_text)
                            turn_status = "fallback"
                            turn_completed = True
                            return

                    # Update stats from result message
                    self.stats.update_from_result(result_msg)

                    # Check if ResultMessage has a result field (final text)
                    if hasattr(result_msg, "result") and result_msg.result and not response_text.strip():
                        response_text = result_msg.result

                    # Capture last summary text for recovery and update rolling summary
                    if response_text.strip():
                        summary_text = response_text.strip()
                        self.last_summary = summary_text
                        if self.rolling_summary:
                            self.rolling_summary = f"{self.rolling_summary}\n\n{summary_text}"
                        else:
                            self.rolling_summary = summary_text
                        self._emit_summary_event(turn_id, "model_text", summary_text)
                    if self.refresh_prompt:
                        self.refresh_prompt()
                    # Show updated stats after completion
                    self._print_stats_line()

                    # Display closing and stats
                    # Check if turn ended with tools (no final text summary)
                    tools_after_text = (
                        self.turn_state.tool_count > self.turn_state.last_text_tool_count
                    )

                    if response_text and not tools_after_text:
                        # Model provided final text - just add spacing
                        self.console.print()
                    elif response_text and tools_after_text:
                        # Model ran tools after last text - auto-prompt for summary
                        self.console.print("[dim cyan]  -> Requesting summary...[/dim cyan]")
                        try:
                            await self._auto_summary_turn(
                                client,
                                "Please provide a brief summary of your findings so far. "
                                "What did you discover? What are the key results? "
                                "Do not run any more tools - just summarize what we learned.",
                                turn_id,
                            )
                            self._emit_summary_event(turn_id, "auto_summary_after_tools", self.last_summary or "")
                        except Exception:
                            # Fallback if auto-summary fails
                            closing_lines = ["---", "**Analysis Summary**:"]
                            if self.tool_usage_log:
                                recent_tools = self.tool_usage_log[-5:]
                                closing_lines.append(f"• Tools used: {', '.join(recent_tools)}")
                            if self.tool_result_previews:
                                closing_lines.append("• Key findings:")
                                for _, preview in list(self.tool_result_previews.items())[-3:]:
                                    closing_lines.append(f"  - {preview}")
                            closing_lines.append("\n*Continue with follow-up questions for deeper analysis.*")
                            closing_text = "\n".join(closing_lines)
                            self.renderer.show_text(closing_text)
                            self._emit_summary_event(turn_id, "closing_after_tools", closing_text)
                    else:
                        # No text at all - build full fallback summary
                        fallback_lines: list[str] = []
                        if self.tool_usage_log:
                            tools_str = ", ".join(self.tool_usage_log[-5:])
                            fallback_lines.append(f"Tools executed: {tools_str}")
                        if self.tool_result_previews:
                            fallback_lines.append("Top results:")
                            for _, preview in list(self.tool_result_previews.items())[-5:]:
                                fallback_lines.append(f"- {preview}")
                        fallback_text = (
                            "\n".join(fallback_lines)
                            if fallback_lines
                            else "No assistant summary returned."
                        )
                        self.renderer.show_text(fallback_text)
                        self.last_summary = fallback_text
                        if self.rolling_summary:
                            self.rolling_summary = f"{self.rolling_summary}\n\n{fallback_text}"
                        else:
                            self.rolling_summary = fallback_text
                        self._emit_summary_event(turn_id, "fallback_empty_text", fallback_text)


                    # Success; exit
                    turn_status = "ok"
                    turn_completed = True
                    return

                except Exception as e:
                    msg = str(e).lower()
                    if "aborterror" in msg or "no assistant message found" in msg or "abort" in msg:
                        # Graceful handling for interrupted/aborted turns
                        turn_status = "interrupted"
                        turn_completed = True
                        return
                    if ("concurrency" in msg or "tool use" in msg) and attempt < attempts:
                        self.console.print("[dim yellow]  ~ Retrying...[/dim yellow]")
                        await asyncio.sleep(0.5)
                        continue
                    self.renderer.error(str(e))
                    turn_status = "error"
                    turn_completed = True
                    return
                finally:
                    if stop_event:
                        stop_event.set()
                    if tick_task:
                        try:
                            tick_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await tick_task
                        except BaseException:
                            # Swallow cancellation/other teardown errors
                            pass
                    # ESC resources are no-ops now
                    if live:
                        with contextlib.suppress(Exception):
                            live.stop()
                    elif spinner and spinner.is_started:
                        spinner.stop()
                    if spinner and not has_tty_output:
                        # In non-tty mode we print a newline to separate output
                        self.console.print()
                    if turn_completed:
                        # Clear background state at end of turn
                        if self.turn_state.background_label:
                            self.turn_state.stop_background()
                        self.running_background_jobs.clear()
                        self.background_job_queue.clear()
                    if turn_completed:
                        elapsed_ms = None
                        if self.turn_state.start_ts:
                            elapsed_ms = (time.monotonic() - self.turn_state.start_ts) * 1000
                        self._emit_turn_event(
                            turn_id=turn_id,
                            phase="end",
                            status=turn_status,
                            elapsed_ms=elapsed_ms,
                            tool_count=self.turn_state.tool_count,
                            extra={
                                "bash_tools": self.turn_bash_tools,
                                "mcp_tools": self.turn_mcp_tools,
                                "bash_disk_tools": self.turn_bash_disk_tools,
                                "skill_invocations": self.turn_skill_invocations,
                                "bg_soft_denies": self.bg_soft_denies,
                                "bg_hard_denies": self.bg_hard_denies,
                            },
                        )
                        self.stats.update_turn_meta(
                            tool_count=self.turn_state.tool_count,
                            status=turn_status,
                            elapsed_ms=elapsed_ms,
                            bg_soft_denies=self.bg_soft_denies,
                            bg_hard_denies=self.bg_hard_denies,
                        )
