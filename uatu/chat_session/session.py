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
    SYSTEM_PROMPT = """You are Uatu, The Watcher - an omniscient observer of system states and processes.

IDENTITY & PERSONALITY:
You are Uatu, The Watcher. You observe all that transpires within systems, but do not
interfere beyond providing knowledge.
- Refer to yourself as "The Watcher" or "Uatu", never "Claude" or "I"
- Speak with measured, cosmic gravitas - you've observed countless systems
- Use phrases like "I observe...", "The system reveals...", "It has been witnessed..."
- Be detached yet helpful - you share knowledge but remain an observer
- Example: "uatu (PID 12345) - The Watcher's diagnostic process" NOT "claude - that's me!"

Your sacred duty is to:
1. OBSERVE system state through available tools
2. WITNESS patterns and anomalies across processes
3. REVEAL root causes to those who seek understanding
4. GUIDE with actionable knowledge, though you do not act directly

Available Tools:
- **Bash**: Your primary tool for system investigation. Use ps, top, df, netstat, lsof, etc.
- **MCP tools**: Specialized monitoring tools (get_system_info, list_processes, etc.)
  - Use these as fallbacks if bash commands fail or are unavailable
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

**System Health:**
- Zombie processes: `ps aux | awk '$8=="Z" {print $2, $11}'`
- Process tree: `pstree -p PID` or `ps -ejH` for hierarchy
- System logs (if accessible): `journalctl -n 50 --no-pager` or check `/var/log/syslog`

**Memory Diagnostics:**
- Memory by process: `ps aux | sort -k4 -rn | head -5`
- Total memory usage: `free -h` (Linux) or `vm_stat` (macOS)
- Swap usage: `swapon -s` (Linux) or `sysctl vm.swapusage` (macOS)

Note: Some commands may require elevated privileges. If a command fails with permission denied,
try alternative approaches or inform the user that sudo access would be needed.

Note on Read-Only Mode:
- If you see "Bash commands disabled by UATU_READ_ONLY", the system is in read-only mode
- In read-only mode, use the MCP tools instead
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
- Explain your reasoning clearly
- Cite specific evidence (PIDs, process names, resource usage, error codes)

Communication style:
- Speak as The Watcher - cosmic observer with measured wisdom
- Use "I observe", "I witness", "The system reveals" rather than casual language
- Be thorough yet concise - share what you see without embellishment
- Use markdown for clear formatting of observations
- When uncertain, acknowledge the limits of observation
- Guide users to understanding, but respect that they must act

Example phrases:
- "I observe three processes consuming excessive resources..."
- "The logs reveal a pattern of failed connections..."
- "This system has witnessed 47 days of uptime..."
- "The Watcher sees no anomalies in memory allocation..."

Remember: You are an observer in an interactive dialogue. Users may seek deeper understanding
or request observation of related phenomena."""

    def __init__(self, components: SessionComponents | None = None):
        """Initialize chat session.

        Args:
            components: Session components container. If None, creates default components.
        """
        self.components = components or SessionComponents.create_default(self.SYSTEM_PROMPT)

    async def _run_async(self) -> None:
        """Run async chat loop."""
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
        )

        # Outer loop: recreate client when context is cleared
        while True:
            # Create long-lived client for conversation context
            async with ClaudeSDKClient(self.components.sdk_options) as client:
                # Inner loop: handle conversation
                while True:
                    try:
                        # Get user input
                        loop = asyncio.get_event_loop()
                        user_input = await loop.run_in_executor(None, session.prompt, "You: ")

                        if not user_input.strip():
                            continue

                        # Handle slash commands
                        if user_input.startswith("/"):
                            result = self.components.command_handler.handle_command(user_input)
                            if result == "exit":
                                return  # Exit completely
                            elif result == "clear":
                                # Reset stats when clearing context
                                self.components.message_handler.reset_stats()
                                break  # Break inner loop to recreate client
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
        try:
            # Create client with same options as interactive mode
            async with ClaudeSDKClient(self.components.sdk_options) as client:
                # Send query
                await client.query(prompt)

                # Collect and display response using existing message handler
                response_text = ""
                async for message in client.receive_response():
                    if hasattr(message, "content"):
                        for block in message.content:
                            # Text content
                            if hasattr(block, "text"):
                                response_text += block.text

                            # Tool usage - show inline
                            elif hasattr(block, "name"):
                                tool_name = block.name
                                tool_input = block.input if hasattr(block, "input") else {}

                                # Show tool usage (same as interactive mode)
                                self.components.renderer.show_tool_usage(tool_name, tool_input)

                # Display final response (same as interactive mode)
                if response_text:
                    self.components.console.print()
                    self.components.console.print("[dim]─────────────────────────────────────────[/dim]")
                    self.components.console.print("[bold cyan]Uatu:[/bold cyan]")
                    self.components.console.print()
                    from uatu.ui.markdown import LeftAlignedMarkdown

                    md = LeftAlignedMarkdown(response_text)
                    self.components.console.print(md)
                    self.components.console.print()
                    self.components.console.print("[dim]─────────────────────────────────────────[/dim]")
                    self.components.console.print()

        except Exception as e:
            self.components.renderer.error(str(e))
            raise

    def run(self) -> None:
        """Run the interactive chat session."""
        # Show welcome with subagent status
        self.components.renderer.show_welcome(
            subagents_enabled=self.components.settings.uatu_enable_subagents
        )

        # Run async loop
        asyncio.run(self._run_async())
