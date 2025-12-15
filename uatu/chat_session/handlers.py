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

    def start(self) -> None:
        self.start_ts = time.monotonic()
        self.tool_count = 0
        self.last_text_tool_count = 0
        self.background_poll_count = 0
        self.background_label = None

    def record_tool(self, tool_name: str) -> None:
        self.tool_count += 1

    def record_text(self) -> None:
        self.last_text_tool_count = self.tool_count

    def record_background_poll(self) -> None:
        self.background_poll_count += 1

    def reset_after_summary(self) -> None:
        self.tool_count = 0
        self.last_text_tool_count = 0
        self.background_poll_count = 0
        self.background_label = None


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
        # Background Bash guard
        self.background_active: bool = False
        self.background_queue: list[str] = []
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
        # Force wrap-up guard
        self.max_tools_per_turn: int = 18
        self.max_tools_per_turn_bg: int = 12
        self.max_elapsed_seconds: float = 120.0
        # Background polling limit for BashOutput
        self.max_bg_polls: int = 3
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
                spinner_text = Text("Pondering... ", style="cyan")
                spinner_text.append(f"{elapsed:0.1f}/{self.max_elapsed_seconds:.0f}s", style="dim")
                if telemetry:
                    spinner_text.append(
                        f" · tools:{telemetry.tool_count}/{self.max_tools_per_turn}", style="dim"
                    )
                if telemetry and telemetry.background_label:
                    spinner_text.append(f" · bg:{telemetry.background_label}", style="dim")
                elif telemetry and telemetry.background_poll_count:
                    spinner_text.append(f" · bg:{telemetry.background_poll_count}", style="dim")
                # Live tokens/cost are only available at ResultMessage; show placeholder
                if self.settings.uatu_show_stats:
                    if self.stats.max_budget_usd and self.stats.total_cost_usd:
                        remaining = max(self.stats.max_budget_usd - self.stats.total_cost_usd, 0)
                        spinner_text.append(f" · budget:${remaining:.4f}", style="dim")
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
        self.background_active = False
        self.background_queue: list[str] = []
        self.turn_seen_basics = set()

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
                        self.console.print("[dim cyan]→ Processing...[/dim cyan]", flush=True)

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
                        tool_cap = self.max_tools_per_turn_bg if self.background_active else self.max_tools_per_turn
                        if (
                            self.turn_state.tool_count >= tool_cap
                            or elapsed >= self.max_elapsed_seconds
                        ) and not response_text:
                            self.renderer.status(
                                "Collected a lot of data; requesting a summary from the model...",
                                status="warning",
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
                                    message_has_text = True
                                    self.turn_state.record_text()

                                # Tool usage (when Claude calls a tool)
                                elif hasattr(block, "name") and hasattr(block, "input"):
                                    if spinner and spinner.is_started:
                                        spinner.stop()

                                    message_has_tools = True
                                    tool_name = block.name
                                    tool_input = block.input if hasattr(block, "input") else None
                                    # If background is active, only allow BashOutput; soft-deny others
                                    # and then hard-deny repeat attempts
                                    if self.background_active and tool_name != Tools.BASH_OUTPUT:
                                        if self.bg_soft_denies == 0:
                                            self.bg_soft_denies += 1
                                            self.renderer.status(
                                                "Background job running; poll BashOutput "
                                                "or summarize before new tools.",
                                                status="warning",
                                                dim=True,
                                            )
                                        else:
                                            self.bg_hard_denies += 1
                                            self.renderer.status(
                                                "Denying additional tools until background completes.",
                                                status="error",
                                                dim=True,
                                            )
                                        continue
                                    # Dedup basics per turn (generic list)
                                    basic_tools = {
                                        Tools.DISK_SCAN_SUMMARY,
                                        Tools.GET_DIRECTORY_SIZES,
                                        Tools.FIND_LARGE_FILES,
                                        "mcp__safe-hints__disk_usage_summary",
                                    }
                                    if tool_name in basic_tools:
                                        if tool_name in self.turn_seen_basics:
                                            self.renderer.status(
                                                "Skipping duplicate basic disk summary this turn.",
                                                status="info",
                                                dim=True,
                                            )
                                            continue
                                        self.turn_seen_basics.add(tool_name)
                                    # Update telemetry
                                    self.turn_state.record_tool(tool_name)
                                    start_ts = time.monotonic()
                                    self.tool_usage_log.append(self.renderer.clean_tool_name(tool_name))
                                    tool_use_id = getattr(block, "id", None)
                                    # Track background Bash to avoid piling on more heavy scans
                                    if (
                                        tool_name == Tools.BASH
                                        and isinstance(tool_input, dict)
                                        and tool_input.get("run_in_background")
                                    ):
                                        cmd_preview = (
                                            tool_input.get("command", "")
                                            if isinstance(tool_input, dict)
                                            else ""
                                        )
                                        if self.background_active:
                                            self.renderer.status(
                                                "Background job already running; finish it before starting another.",
                                                status="warning",
                                                dim=True,
                                            )
                                            continue
                                        else:
                                            self.background_active = True
                                            # Set a concise background label from command
                                            if cmd_preview:
                                                cmd_preview = cmd_preview.split("\n", 1)[0]
                                                if len(cmd_preview) > 40:
                                                    cmd_preview = cmd_preview[:37] + "..."
                                                self.turn_state.background_label = cmd_preview
                                            else:
                                                self.turn_state.background_label = (
                                                    self.renderer.clean_tool_name(tool_name)
                                                )
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

                                    # Show tool usage with enhanced display
                                    self.renderer.show_tool_usage(tool_name, tool_input)

                                # Tool result (when tool execution completes)
                                # These come in UserMessage blocks via receive_messages()
                                elif hasattr(block, "tool_use_id") and hasattr(block, "content"):
                                    tool_use_id = block.tool_use_id
                                    tool_response = block.content

                                    # Look up the tool name from our tracking map
                                    tool_name = self.tool_use_map.get(tool_use_id, "unknown")
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

                                    # Background polling count
                                    if tool_name == Tools.BASH_OUTPUT:
                                        self.turn_state.record_background_poll()
                                        # Receiving BashOutput means we can consider background complete
                                        self.background_active = False
                                        self.turn_state.background_label = None
                                        # Launch queued job label display only
                                        # (actual execution would be driven by model)
                                        if self.background_queue:
                                            next_label = self.background_queue.pop(0)
                                            self.turn_state.background_label = next_label
                                            self.renderer.status(
                                                f"Background queue progressed: now running queued job ({next_label})",
                                                status="info",
                                                dim=True,
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
                                "Background command still running; proceeding with available data.",
                                status="warning",
                                dim=True,
                            )
                            break

                    # If no ResultMessage arrived (e.g., aborted/timeout), synthesize a fallback summary
                    if not result_msg:
                        self.renderer.status(
                            "No final summary returned; synthesizing from tool activity.",
                            status="warning",
                            dim=True,
                        )
                        fallback_lines: list[str] = []
                        if response_text.strip():
                            fallback_lines.append(response_text.strip())
                        if self.tool_usage_log:
                            tools_str = ", ".join(self.tool_usage_log[-8:])
                            fallback_lines.append(f"Tools executed: {tools_str}")
                        if self.tool_result_previews:
                            fallback_lines.append("Top results:")
                            for _, preview in list(self.tool_result_previews.items())[-8:]:
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
                        self._emit_summary_event(turn_id, "fallback_no_result", fallback_text)
                        # Skip normal stats update since we lack a ResultMessage
                        turn_status = "fallback"
                        turn_completed = True
                        self.background_active = False
                        self.background_queue.clear()
                        self.turn_state.background_label = None
                        return

                    # Update stats from result message
                    self.stats.update_from_result(result_msg)
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

                    # Display closing and stats (text was already streamed)
                    if response_text:
                        self.console.print()
                    else:
                        # Build a fallback summary if model returned no text
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
                        self.renderer.status(
                            "Retrying after transient tool concurrency error...", status="warning", dim=True
                        )
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
                        self.background_active = False
                        self.background_queue.clear()
                        self.turn_state.background_label = None
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
