"""Command-line interface for Uatu."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from uatu.agent import UatuAgent
from uatu.capabilities import ToolCapabilities
from uatu.chat import UatuChat
from uatu.tools import ProcessAnalyzer, create_tool_registry
from uatu.watcher import AsyncWatcher, Watcher

app = typer.Typer(
    name="uatu",
    help="Uatu - The Watcher: An agentic system troubleshooting tool",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """
    Start Uatu in interactive mode (default) or run a specific command.

    If no command is provided, starts an interactive chat session.
    """
    if ctx.invoked_subcommand is None:
        # No subcommand provided, start interactive mode
        try:
            chat = UatuChat()
            chat.run()
        except Exception as e:
            console.print(f"[red]Error starting chat: {e}[/red]")
            console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
            raise typer.Exit(1)


@app.command()
def check() -> None:
    """Run a quick system health check."""
    console.print("[bold blue]Uatu - The Watcher[/bold blue]")
    console.print("Performing system health check...\n")

    analyzer = ProcessAnalyzer()

    # System summary
    summary = analyzer.get_system_summary()
    table = Table(title="System Resources")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("CPU Usage", f"{summary['cpu_percent']:.1f}%")
    table.add_row("Memory Usage", f"{summary['memory_percent']:.1f}%")
    table.add_row(
        "Memory Used",
        f"{summary['memory_used_gb']:.1f} GB / {summary['memory_total_gb']:.1f} GB",
    )
    table.add_row("Process Count", str(summary["process_count"]))

    console.print(table)
    console.print()

    # Check for issues
    issues = []

    # High CPU
    high_cpu = analyzer.find_high_cpu_processes(threshold=20.0)
    if high_cpu:
        issues.append(f"Found {len(high_cpu)} processes using >20% CPU")

    # High memory
    high_mem = analyzer.find_high_memory_processes(threshold_mb=1000.0)
    if high_mem:
        issues.append(f"Found {len(high_mem)} processes using >1GB memory")

    # Zombies
    zombies = analyzer.find_zombie_processes()
    if zombies:
        issues.append(f"Found {len(zombies)} zombie processes")

    if issues:
        console.print("[bold yellow]⚠️  Issues Detected:[/bold yellow]")
        for issue in issues:
            console.print(f"  • {issue}")
    else:
        console.print("[bold green]✓ No major issues detected[/bold green]")


@app.command()
def investigate(symptom: str) -> None:
    """
    Investigate a system issue using the AI agent.

    Args:
        symptom: Description of the problem or symptom to investigate
    """
    console.print(Panel.fit("[bold blue]Uatu - The Watcher[/bold blue]"))
    console.print(f"\n[dim]Investigating:[/dim] {symptom}\n")

    # Track if we're in the middle of tool execution
    current_tool = None

    def on_investigation_event(event_type: str, data: dict) -> None:
        """Handle streaming events from the agent."""
        nonlocal current_tool

        if event_type == "tool_use":
            # Show tool being called
            tool_name = data["name"]
            tool_input = data["input"]
            current_tool = tool_name

            # Format tool call like Claude Code
            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                desc = tool_input.get("description", "")
                console.print(f"[dim]> {desc or cmd}[/dim]")
            else:
                console.print(f"[dim]> Using tool: {tool_name}[/dim]")

        elif event_type == "tool_result":
            # Tool finished - clear current tool
            current_tool = None

        elif event_type == "error":
            console.print(f"[red]Error: {data['message']}[/red]")

    async def run_investigation():
        agent = UatuAgent()
        return await agent.investigate(symptom, on_event=on_investigation_event)

    result, stats = asyncio.run(run_investigation())

    console.print("\n[bold cyan]Analysis:[/bold cyan]")
    # Use left-aligned markdown rendering
    from rich.markdown import Markdown as RichMarkdown

    md = RichMarkdown(result)
    # Override heading justification to left-align all headings
    for element in md.elements:
        if hasattr(element, 'justify'):
            element.justify = "left"

    console.print(md)

    # Display token usage and stats (Claude Code style)
    console.print()
    stats.display_summary()


@app.command()
def processes(
    high_cpu: bool = typer.Option(False, "--high-cpu", help="Show high CPU processes"),
    high_memory: bool = typer.Option(False, "--high-memory", help="Show high memory processes"),
    zombies: bool = typer.Option(False, "--zombies", help="Show zombie processes"),
) -> None:
    """Show process information."""
    analyzer = ProcessAnalyzer()

    if high_cpu:
        procs = analyzer.find_high_cpu_processes(threshold=5.0)
        table = Table(title="High CPU Processes (>5%)")
        table.add_column("PID", style="cyan")
        table.add_column("User", style="yellow")
        table.add_column("CPU %", style="red")
        table.add_column("Memory (MB)", style="magenta")
        table.add_column("Command", style="green")

        for proc in procs[:10]:  # Top 10
            table.add_row(
                str(proc.pid),
                proc.user,
                f"{proc.cpu_percent:.1f}",
                f"{proc.memory_mb:.1f}",
                " ".join(proc.cmdline[:3]) + ("..." if len(proc.cmdline) > 3 else ""),
            )

        console.print(table)

    elif high_memory:
        procs = analyzer.find_high_memory_processes(threshold_mb=100.0)
        table = Table(title="High Memory Processes (>100MB)")
        table.add_column("PID", style="cyan")
        table.add_column("User", style="yellow")
        table.add_column("Memory (MB)", style="red")
        table.add_column("CPU %", style="magenta")
        table.add_column("Command", style="green")

        for proc in procs[:10]:  # Top 10
            table.add_row(
                str(proc.pid),
                proc.user,
                f"{proc.memory_mb:.1f}",
                f"{proc.cpu_percent:.1f}",
                " ".join(proc.cmdline[:3]) + ("..." if len(proc.cmdline) > 3 else ""),
            )

        console.print(table)

    elif zombies:
        procs = analyzer.find_zombie_processes()
        if not procs:
            console.print("[green]No zombie processes found[/green]")
            return

        table = Table(title="Zombie Processes")
        table.add_column("PID", style="cyan")
        table.add_column("Name", style="yellow")
        table.add_column("Parent PID", style="magenta")
        table.add_column("Command", style="green")

        for proc in procs:
            table.add_row(
                str(proc.pid),
                proc.name,
                str(proc.parent_pid) if proc.parent_pid else "N/A",
                " ".join(proc.cmdline[:3]) + ("..." if len(proc.cmdline) > 3 else ""),
            )

        console.print(table)

    else:
        # Default: show process tree
        tree = analyzer.get_process_tree()
        console.print("[bold]Process Tree:[/bold]")
        console.print(tree[:2000])  # Limit output
        if len(tree) > 2000:
            console.print("\n[dim]... output truncated ...[/dim]")


@app.command()
def watch(
    interval: int = typer.Option(
        10, "--interval", "-i", help="Observation interval in seconds (sync mode only)"
    ),
    baseline: int = typer.Option(
        5, "--baseline", "-b", help="Baseline learning duration in minutes (use 1 for fast testing)"
    ),
    log_file: Path = typer.Option(
        Path.home() / ".uatu" / "events.jsonl",
        "--log",
        "-l",
        help="Event log file path",
    ),
    investigate: bool = typer.Option(
        False,
        "--investigate",
        help="Use LLM to investigate anomalies (Phase 2)",
    ),
    async_mode: bool = typer.Option(
        True,
        "--async/--sync",
        help="Use async event-driven architecture (recommended)",
    ),
) -> None:
    """
    Watch the system continuously and detect anomalies.

    Async mode (default): Event-driven, multiple concurrent watchers.
    Sync mode (--sync): Legacy polling-based watcher.

    Phase 1 (default): Detects anomalies using local heuristics only.
    Phase 2 (--investigate): Uses Claude to investigate and explain anomalies.

    Examples:
        # Fast testing (1 minute baseline)
        uatu watch --baseline 1

        # Production (5 minute baseline, default)
        uatu watch

        # With investigation
        uatu watch --baseline 1 --investigate
    """
    try:
        if async_mode:
            # Use async event-driven watcher (recommended)
            watcher = AsyncWatcher(
                interval_seconds=interval,  # Not used in async mode
                baseline_duration_minutes=baseline,
                investigate=investigate,
                log_file=log_file,
            )
            asyncio.run(watcher.start())
        else:
            # Use legacy sync watcher
            watcher = Watcher(
                interval_seconds=interval,
                baseline_duration_minutes=baseline,
                log_file=log_file,
                investigate=investigate,
            )
            asyncio.run(watcher.start())
    except KeyboardInterrupt:
        console.print("\n[yellow]Watcher stopped by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def events(
    log_file: Path = typer.Option(
        Path.home() / ".uatu" / "events.jsonl",
        "--log",
        "-l",
        help="Event log file to read",
    ),
    last: int = typer.Option(10, "--last", "-n", help="Show last N events"),
) -> None:
    """Show recent anomaly events detected by the watcher."""
    import json

    if not log_file.exists():
        console.print(f"[yellow]No events found at {log_file}[/yellow]")
        console.print("[dim]Start watching with: uatu watch[/dim]")
        return

    # Read events
    events_list = []
    try:
        with open(log_file) as f:
            for line in f:
                events_list.append(json.loads(line))
    except Exception as e:
        console.print(f"[red]Error reading log file: {e}[/red]")
        return

    if not events_list:
        console.print("[green]No anomalies detected yet![/green]")
        return

    # Show last N events
    recent_events = events_list[-last:]

    table = Table(title=f"Recent Anomaly Events ({len(recent_events)})")
    table.add_column("Time", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Severity", style="red")
    table.add_column("Message", style="white")

    for event in recent_events:
        severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🔴"}.get(event["severity"], "")

        timestamp = event["timestamp"].split("T")[1].split(".")[0]  # HH:MM:SS

        table.add_row(
            timestamp,
            event["type"],
            f"{severity_emoji} {event['severity']}",
            event["message"][:60],
        )

    console.print(table)

    # Show summary
    console.print()
    console.print(f"[dim]Total events logged: {len(events_list)}[/dim]")
    console.print(f"[dim]Log file: {log_file}[/dim]")


@app.command()
def tools() -> None:
    """Show available tools and system capabilities."""
    console.print(Panel.fit("[bold blue]Uatu Tool Discovery[/bold blue]"))
    console.print()

    # Detect capabilities
    caps = ToolCapabilities.detect()

    # Show environment
    env_table = Table(title="Environment")
    env_table.add_column("Property", style="cyan")
    env_table.add_column("Value", style="green")

    env_table.add_row("Has /proc", "✓" if caps.has_proc else "✗")
    env_table.add_row("Has /sys", "✓" if caps.has_sys else "✗")
    env_table.add_row("In Container", "Yes" if caps.in_container else "No")
    env_table.add_row("Root Access", "Yes" if caps.is_root else "No")

    console.print(env_table)
    console.print()

    # Show available commands
    cmd_table = Table(title="Available Commands")
    cmd_table.add_column("Tier", style="yellow")
    cmd_table.add_column("Command", style="cyan")
    cmd_table.add_column("Status", style="green")

    commands = [
        (1, "ps", caps.has_ps),
        (1, "lsof", caps.has_lsof),
        (2, "ss", caps.has_ss),
        (2, "netstat", caps.has_netstat),
        (2, "systemctl", caps.has_systemctl),
        (2, "journalctl", caps.has_journalctl),
        (3, "strace", caps.has_strace),
    ]

    for tier, cmd, available in commands:
        status = "✓ Available" if available else "✗ Not found"
        cmd_table.add_row(str(tier), cmd, status)

    console.print(cmd_table)
    console.print()

    # Show registered tools
    registry = create_tool_registry(caps)

    tools_table = Table(title=f"Registered Tools ({len(registry.list_available_tools())})")
    tools_table.add_column("Tool Name", style="cyan")
    tools_table.add_column("Tier", style="yellow")
    tools_table.add_column("Description", style="white")

    for tool_name in sorted(registry.list_available_tools()):
        tool = registry.get_tool(tool_name)
        if tool:
            meta = tool.metadata
            desc = meta.description[:60] + "..." if len(meta.description) > 60 else meta.description
            tools_table.add_row(tool_name, f"Tier {meta.tier}", desc)

    console.print(tools_table)


if __name__ == "__main__":
    app()
