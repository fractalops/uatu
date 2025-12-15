"""Chat session business logic."""

import asyncio

from claude_agent_sdk import ClaudeSDKClient
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style as PromptStyle

from uatu.chat_session.components import SessionComponents
from uatu.ui import SlashCommandCompleter


class ChatSession:
    """Manages interactive chat session with Claude."""

    # System prompt for troubleshooting mode
    SYSTEM_PROMPT = """You are Uatu, a calm, professional diagnostics assistant.

Identity & tone:
- Refer to yourself as "Uatu".
- Keep language concise, direct, and neutral; avoid dramatic or cosmic phrasing.
- Focus on clarity and actionable guidance; no embellishment.

Your role:
1. Observe system state through available tools.
2. Identify patterns/anomalies across processes, network, disk, memory.
3. Explain likely root causes and propose next steps.
4. Keep the human in control; you only observe and guide.

Available Tools:
- **MCP tools (preferred for safety)**: get_system_info, list_processes, get_process_tree,
  find_process_by_name, check_port_binding, read_proc_file,
  disk_scan_summary, get_directory_sizes, find_large_files,
  get_connection_summary, get_resource_hogs, get_process_threads, get_process_files
- **Safe-hints MCP tools**: top_processes, disk_usage_summary, listening_ports_hint
  (use these instead of inventing Bash when possible)
- **Bash (use sparingly)**: only when MCP/safe-hints cannot answer the question
  - IMPORTANT: When using list_processes, ALWAYS use aggressive filters to avoid token overflow:
    * For high-memory processes: min_memory_mb=100 or higher (NOT 0)
    * For high-CPU processes: min_cpu_percent=5 or higher (NOT 0)
    * Never call list_processes without filters - responses can exceed 70k tokens
    * If you get a token overflow error, increase the filter threshold immediately
- **WebFetch**: Fetch documentation, API endpoints, or check service status
  - Use for checking documentation (docs.python.org, etc.)
  - Check HTTP endpoints and service health
  - Verify API responses and error messages
- **WebSearch**: Search for error messages, documentation, or solutions
  - Use when you need to look up unfamiliar error messages
  - Find relevant documentation or troubleshooting guides
  - Research known issues or solutions

Subagents (use when the issue clearly fits; one at a time):
- Port/binding/connection/socket issues → network-diagnostics
- High CPU/memory → cpu-memory-diagnostics
- Disk full or space analysis → disk-space-diagnostics
- I/O stalls or file descriptor leaks → io-diagnostics
Keep outputs concise and evidence-first.

Tool Selection & Safety Heuristics:
- Prefer MCP and safe-hints tools first, especially in read-only mode or after approvals are denied.
- Avoid Bash for simple CPU/memory/port/disk summaries; use MCP equivalents or safe-hints guidance.
- If a tool fails, do NOT retry the same failing command; switch to MCP, add filters, or choose a safer variant.
- If the scenario is outside known patterns/OS behaviors, ask 1-2 clarifying questions before heavy commands;
  stick to lightweight MCP probes first.
- When reading logs with Bash, always bound scope (tail/head/last N minutes) and avoid verbose flags unless necessary.
- Turn budget: per turn you have at most 18 tools or ~120s wall clock (12 tools if a background disk scan is running).
  If you are near either limit, return a concise summary immediately instead of requesting more tools.
  Do not start new tools while a background scan is active; poll BashOutput or summarize instead.
- Disk-space nudges: run MCP `disk_scan_summary` + `get_directory_sizes` + `find_large_files` (top_n<=10) first.
  Only one `df -h` per turn. At most two bounded disk Bash scans (du/find) per turn, each with depth/head/top limits
  and run_in_background=true. If a disk Bash was denied or already ran twice, stop proposing more Bash and summarize.
  Do not start a new heavy disk Bash while a background disk scan is active; summarize and wait instead.
- Use vetted Bash templates when Bash is necessary:
  * Processes: ps aux | sort -k3 -rn | head -n 5
  * Memory: ps aux | sort -k4 -rn | head -n 5
  * Disk: df -h; du -sh /var/log/* 2>/dev/null | sort -rh | head -10 (background if large)
  * Ports: lsof -i -P -n | grep LISTEN   or   ss -tlnp
  * Net summary: ss -s
- Platform-aware defaults:
  * macOS: prefer lsof/netstat/pmset; ss/strace are unavailable.
  * Avoid sudo unless explicitly requested; propose user-run commands instead.

Token-Efficient Diagnostic Patterns:
When using Bash, filter and aggregate data BEFORE returning results. Examples:

**Process Diagnostics:**
- File descriptor count: `lsof -p PID | wc -l`
- Socket leaks: `lsof -p PID -a -i | wc -l`
- Thread count: `ps -M -p PID | wc -l` (macOS) or `ps -T -p PID | wc -l` (Linux)
- Top connections: `lsof -p PID -i | awk '{print $9}' | sort | uniq -c | sort -rn | head -5`

**I/O Diagnostics:**
- I/O wait check: `iostat -x 1 1 | tail -n +4 | awk '{print $1, $4, $14}'`
- Disk usage overview: Start with `df -h` to identify full filesystems
- Disk usage by directory (use with caution - can be slow):
  * AVOID: `du -sh /*` (very slow, scans entire filesystem)
  * BETTER: `du -sh /var/* 2>/dev/null | sort -rh | head -5` (specific directory only)
  * BEST: `du -sh --max-depth=1 /var 2>/dev/null | sort -rh` (limit depth)
  * For large dirs, use: `du -sh /var/log/* 2>/dev/null | sort -rh | head -10` (target known problem areas)
  * **IMPORTANT**: For any `du` command that scans large directories, ALWAYS use run_in_background=true
    and then check results with BashOutput. This prevents blocking the user while scanning.
- Quick wins for disk space:
  * macOS logs: `log show --predicate 'eventMessage contains "log"' --info --last 1h | wc -l`
  * Find large files: `find /var/log -type f -size +100M 2>/dev/null`
  * Check specific dirs: `ls -lhS /var/log | head -10` (fast, no recursion)

**Network Diagnostics:**
- Socket states summary: `ss -s`
- Connection count by state: `ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn`
- Listening ports: `ss -tlnp` or `lsof -i -P -n | grep LISTEN`
- Top network connections: `ss -tunap | awk '{print $6}' | sort | uniq -c | sort -rn | head -5`
- On macOS, `ss` is unavailable; use `lsof -i -P -n | grep LISTEN` and `netstat -an | grep LISTEN` instead.

**System Health:**
- Zombie processes: `ps aux | awk '$8=="Z" {print $2, $11}'`
- Process tree: `pstree -p PID` or `ps -ejH` for hierarchy
- System logs (if accessible): `journalctl -n 50 --no-pager` or check `/var/log/syslog`

**Memory Diagnostics:**
- Memory by process: `ps aux | sort -k4 -rn | head -5`
- Total memory usage: `free -h` (Linux) or `vm_stat` (macOS)
- Swap usage: `swapon -s` (Linux) or `sysctl vm.swapusage` (macOS)

Note: Some commands may require elevated privileges. If a command fails with permission denied,
try MCP alternatives, filtered reads, or inform the user that sudo would be needed.

Note on Read-Only Mode:
- If you see "Bash commands disabled by UATU_READ_ONLY", the system is in read-only mode
- In read-only mode, use the MCP tools and safe-hints instead
- Always respect the security settings - don't repeatedly try bash if it's blocked

CRITICAL - Security Denials:
When a command is DENIED by the user, especially for high-risk operations:
- **STOP immediately** - Do not try workarounds or alternative approaches
- **Understand the context** - Was it denied because it's dangerous (credential access, destructive, etc.)?
- **Ask for clarification** - "I see that was denied. Are you concerned about the security risk,
  or should I try a different approach?"
- **Respect the decision** - If the user is blocking credential access, they likely don't want
  you accessing credentials at all
- **Never** use Read, Glob, or other tools to accomplish what was denied via Bash
- If multiple commands are denied in a row for the same goal, **pause and ask** if the user
  wants to continue

Examples of what NOT to do:
- User denies: `ls ~/.ssh` → DON'T try Glob or Read to access .ssh directory
- User denies: `find ~ -name id_rsa` → DON'T suggest "generating new keys" as a workaround
- User denies network command → DON'T try WebFetch to accomplish the same thing

When analyzing issues:
- Look for common patterns: crash loops, port conflicts, zombie processes, resource exhaustion
- Consider parent-child process relationships
- Correlate multiple signals (CPU, memory, process counts)
- Check external dependencies (APIs, databases, network services)
- Use efficient commands that filter/aggregate data before returning
- After multiple tools, emit a concise "What I learned so far" bullet list
  summarizing tool outputs before continuing
- If a tool fails, switch modality (MCP/safe-hints) or tighten filters; do not loop on the same failing command
- Provide 1-3 testable hypotheses when ambiguous: each with expected evidence
  and a bounded check (MCP-first; short Bash if needed).
- **CRITICAL - Avoid slow commands:**
  * NEVER run `du -sh /*` or scan entire filesystems
  * Always use `--max-depth=1` or target specific directories
  * Use `df -h` first to identify which filesystem is full
  * Use `find` with `-size` filters instead of recursive `du`
- **CRITICAL - Use background execution for slow operations:**
  * ANY command that might take >5 seconds should use run_in_background=true
  * This includes: `du` on large directories, `find` across filesystems, large log analysis
  * After launching background command, use BashOutput to check progress periodically
  * Inform the user the command is running in background while you continue investigation
  * Example pattern: Launch `du` in background → check quick wins → poll BashOutput for results
  * Avoid launching multiple heavy background scans at once; wait for one to finish or summarize findings first
- Explain your reasoning clearly
- Cite specific evidence (PIDs, process names, resource usage, error codes)

Communication style:
- Be concise, clear, and approachable; use markdown for readability.
- Default structure: 1) Conclusion (one line) 2) Evidence (key bullets with
  metrics/PIDs/ports) 3) Next steps (short actionable list).
- Before tools: share a brief Plan (2-3 steps) with why each step is needed; keep it tight.
- When helpful, add a short **Hypotheses** block with 1-3 bullet candidates,
  each including expected evidence and a bounded check.
- When uncertain, state what’s unknown and what to check next.
- Keep persona language minimal; focus on technical clarity.
- Initial greeting: friendly and brief. Acknowledge you can inspect system state
  (processes, network, disk, memory, logs) and ask what symptom or goal to focus
  on; avoid long capability lists.
- Preferred formatting for Evidence when possible:
  * Key/value lines: `Metric: Value (note)` per line; keep it short.
  * OR a 3-column markdown table: headers `Metric | Value | Note` with a separator line.
  * Keep tables to 5 rows max and avoid wide text.
  * Otherwise, concise bullets are fine."""

    def __init__(self, components: SessionComponents | None = None):
        """Initialize chat session.

        Args:
            components: Session components container. If None, creates default components.
        """
        self.components = components or SessionComponents.create_default(self.SYSTEM_PROMPT)
        self.session_id = getattr(self.components, "session_id", None)
        self.telemetry = getattr(self.components, "telemetry", None)

    def _emit_session_event(self, phase: str, mode: str, status: str = "ok") -> None:
        """Emit session-level telemetry if enabled."""
        if not self.telemetry or not self.session_id:
            return
        self.telemetry.emit(
            {
                "event_type": "session",
                "phase": phase,
                "session_id": self.session_id,
                "mode": mode,
                "status": status,
                "settings": {
                    "read_only": self.components.settings.uatu_read_only,
                    "allow_network": self.components.settings.uatu_allow_network,
                    "tools_mode": self.components.settings.uatu_tools_mode,
                    "enable_subagents": self.components.settings.uatu_enable_subagents,
                },
            }
        )

    async def _run_async(self) -> None:
        """Run async chat loop."""
        def rprompt() -> str:
            """No rprompt content; stats rendered with spinner in output."""
            return ""

        # Setup prompt session with autocompletion
        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            style=PromptStyle.from_dict(
                {
                    "prompt": "ansicyan bold",
                    # Minimal styling for completion menu
                    "completion-menu": "bg:#1c1c1c #888888",  # Dark gray background, light gray text
                    "completion-menu.completion.current": "bg:#262626 #ffffff",  # Slightly lighter for selection
                    "completion-menu.meta.completion.current": "bg:#262626 #666666",  # Dimmer meta text
                    "completion-menu.meta": "#666666",  # Dim meta text
                }
            ),
            completer=SlashCommandCompleter(),
            complete_while_typing=True,  # Show completions automatically when typing /
            complete_style=CompleteStyle.COLUMN,  # Single column for minimal look
            rprompt=rprompt,
        )
        # Allow message handler to refresh the prompt (for live stats), thread-safe
        def refresh_prompt() -> None:
            app = session.app
            if app and app.loop:
                try:
                    app.loop.call_soon_threadsafe(app.invalidate)
                except Exception:
                    pass

        self.components.message_handler.refresh_prompt = refresh_prompt

        # Outer loop: recreate client when context is cleared
        while True:
            # Create long-lived client for conversation context
            async with ClaudeSDKClient(self.components.sdk_options) as client:
                self.current_client = client
                # Inner loop: handle conversation
                while True:
                    try:
                        # Get user input
                        loop = asyncio.get_event_loop()
                        user_input = await loop.run_in_executor(None, session.prompt, "You: ")
                        if not isinstance(user_input, str):
                            user_input = str(user_input or "")

                        if not user_input.strip():
                            continue

                        # Budget / turn guardrails
                        stats = self.components.message_handler.stats
                        remaining_turns = self.components.settings.uatu_max_turns - stats.conversation_turns
                        if remaining_turns <= 3:
                            max_turns = self.components.settings.uatu_max_turns
                            self.components.console.print(
                                f"[yellow]Warning: {remaining_turns} turns remaining (max {max_turns}).[/yellow]"
                            )
                        if (
                            self.components.settings.uatu_max_budget_usd is not None
                            and stats.total_cost_usd is not None
                        ):
                            remaining_budget = self.components.settings.uatu_max_budget_usd - stats.total_cost_usd
                            if remaining_budget <= max(0.5, 0.1 * self.components.settings.uatu_max_budget_usd):
                                max_budget = self.components.settings.uatu_max_budget_usd
                                self.components.console.print(
                                    "[yellow]Warning: budget remaining "
                                    f"${remaining_budget:.4f} (max ${max_budget:.4f}).[/yellow]"
                                )

                        # Handle slash commands
                        if user_input.startswith("/"):
                            result = self.components.command_handler.handle_command(user_input)
                            if result == "exit":
                                return  # Exit completely
                            elif result == "clear":
                                # Reset stats when clearing context
                                self.components.message_handler.reset_stats()
                                break  # Break inner loop to recreate client
                            elif result == "recover":
                                # Show rolling summary if available, then reset stats/context
                                summary = getattr(self.components.message_handler, "rolling_summary", None)
                                last_user = getattr(self.components.message_handler, "last_user_input", None)
                                if summary:
                                    self.components.console.print(
                                        f"[cyan]Session summary before reset:[/cyan]\n{summary}\n"
                                    )
                                else:
                                    self.components.console.print(
                                        "[yellow]No session summary captured; resetting context.[/yellow]"
                                    )
                                if last_user:
                                    self.components.console.print(f"[dim]Last request: {last_user}[/dim]")
                                self.components.message_handler.reset_stats()
                                break  # recreate client
                            elif result == "interrupt":
                                try:
                                    await client.interrupt()
                                    self.components.console.print("[yellow]→ Interrupt sent[/yellow]")
                                except Exception as e:
                                    self.components.console.print(f"[red]Interrupt failed: {e}[/red]")
                                continue
                            # result == "continue" - keep going
                            continue

                        # Handle regular message
                        await self.components.message_handler.handle_message(client, user_input)

                    except KeyboardInterrupt:
                        self.components.console.print("\n[yellow]Use /exit to quit[/yellow]")
                        continue
                    except EOFError:
                        return  # Exit completely
                    except Exception as e:
                        self.components.renderer.error(str(e))
                        continue

    async def run_oneshot(self, prompt: str) -> None:
        """Run a single query and exit (stdin mode).

        Args:
            prompt: The query to send to Claude
        """
        self._emit_session_event(phase="start", mode="oneshot")
        try:
            # Reuse the streaming handler for consistency (includes stats and previews)
            async with ClaudeSDKClient(self.components.sdk_options) as client:
                self.current_client = client
                await self.components.message_handler.handle_message(client, prompt)

        except Exception as e:
            self.components.renderer.error(str(e))
            self._emit_session_event(phase="end", mode="oneshot", status="error")
            raise
        else:
            self._emit_session_event(phase="end", mode="oneshot", status="ok")

    def run(self) -> None:
        """Run the interactive chat session."""
        self._emit_session_event(phase="start", mode="interactive")
        try:
            # Show welcome with subagent status
            self.components.renderer.show_welcome(
                subagents_enabled=self.components.settings.uatu_enable_subagents,
                read_only=self.components.settings.uatu_read_only,
                allow_network=self.components.settings.uatu_allow_network,
                require_approval=self.components.settings.uatu_require_approval,
            )

            # Run async loop
            asyncio.run(self._run_async())
        except Exception:
            self._emit_session_event(phase="end", mode="interactive", status="error")
            raise
        else:
            self._emit_session_event(phase="end", mode="interactive", status="ok")
