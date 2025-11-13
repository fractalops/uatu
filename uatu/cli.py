"""Command-line interface for Uatu."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from uatu.agent import UatuAgent
from uatu.chat import LeftAlignedMarkdown, UatuChat
from uatu.watcher import AsyncWatcher, Watcher

app = typer.Typer(
    name="uatu",
    help="Uatu - The Watcher: Agentic system troubleshooting powered by Claude",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """
    Start Uatu in interactive chat mode (default) or run a specific command.

    Interactive mode lets you troubleshoot conversationally with Claude.
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
def investigate(symptom: str) -> None:
    """
    Investigate a system issue using AI-powered analysis.

    The agent will gather system information, analyze logs, and provide
    root cause analysis with actionable remediation steps.

    Args:
        symptom: Description of the problem (e.g., "high CPU usage", "server slow")
    """
    console.print(Panel.fit("[bold blue]Uatu - The Watcher[/bold blue]"))
    console.print(f"\n[dim]Investigating:[/dim] {symptom}\n")

    def on_investigation_event(event_type: str, data: dict) -> None:
        """Handle streaming events from the agent."""
        if event_type == "tool_use":
            # Show tool being called
            tool_name = data["name"]
            tool_input = data["input"]

            # Bash commands: Show description + command
            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                desc = tool_input.get("description", "")

                # Show description if available
                if desc:
                    console.print(f"[dim]→ {desc}[/dim]")

                # Show command preview
                cmd_preview = cmd[:120]
                if len(cmd) > 120:
                    cmd_preview += "..."
                console.print(f"[dim]  $ {cmd_preview}[/dim]")

            # MCP tools: Show with MCP prefix and parameters
            elif tool_name.startswith("mcp__"):
                # Clean up name: mcp__system-tools__get_system_info -> Get System Info
                clean_name = tool_name.split("__")[-1].replace("_", " ").title()
                console.print(f"[dim]→ MCP: {clean_name}[/dim]")

                # Show key parameters if available
                if tool_input:
                    # Show first 3 parameters
                    params = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:3])
                    if params:
                        console.print(f"[dim]   ({params})[/dim]")

            # Other tools: Simple display
            else:
                console.print(f"[dim]→ {tool_name}[/dim]")

        elif event_type == "error":
            console.print(f"[red]Error: {data['message']}[/red]")

    async def run_investigation():
        agent = UatuAgent()
        return await agent.investigate(symptom, on_event=on_investigation_event)

    result, stats = asyncio.run(run_investigation())

    console.print("\n[bold cyan]Analysis:[/bold cyan]")
    # Use left-aligned markdown rendering
    md = LeftAlignedMarkdown(result)
    console.print(md)

    # Display token usage and stats
    console.print()
    stats.display_summary()


@app.command()
def watch(
    interval: int = typer.Option(10, "--interval", "-i", help="Observation interval in seconds (sync mode only)"),
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
        help="Use LLM to investigate anomalies",
    ),
    investigate_level: str = typer.Option(
        "warning",
        "--investigate-level",
        help="Minimum severity to investigate: info, warning, error, critical",
    ),
    investigation_log: Path = typer.Option(
        Path.home() / ".uatu" / "investigations.jsonl",
        "--investigation-log",
        help="Investigation log file path",
    ),
    async_mode: bool = typer.Option(
        True,
        "--async/--sync",
        help="Use async event-driven architecture (recommended)",
    ),
) -> None:
    """Watch the system continuously and detect anomalies.

    Async mode (default): Event-driven, multiple concurrent watchers.
    Sync mode (--sync): Legacy polling-based watcher.

    Examples:
        # Fast testing (1 minute baseline)
        uatu watch --baseline 1

        # Production (5 minute baseline, default)
        uatu watch

        # With investigation (WARNING+ severity)
        uatu watch --baseline 1 --investigate

        # Investigate all severity levels
        uatu watch --investigate --investigate-level info
    """
    # Parse severity level
    from uatu.watcher.models import Severity

    severity_map = {
        "info": Severity.INFO,
        "warning": Severity.WARNING,
        "error": Severity.ERROR,
        "critical": Severity.CRITICAL,
    }

    # Validate severity level
    if investigate_level.lower() not in severity_map:
        console.print(f"[red]Invalid investigate-level: '{investigate_level}'[/red]")
        console.print(f"[dim]Valid options: {', '.join(severity_map.keys())}[/dim]")
        raise typer.Exit(1)

    investigate_severity = severity_map[investigate_level.lower()]

    try:
        if async_mode:
            # Use async event-driven watcher (recommended)
            watcher = AsyncWatcher(
                interval_seconds=interval,  # Not used in async mode
                baseline_duration_minutes=baseline,
                investigate=investigate,
                investigate_level=investigate_severity,
                log_file=log_file,
                investigation_log_file=investigation_log,
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
def investigations(
    log_file: Path = typer.Option(
        Path.home() / ".uatu" / "investigations.jsonl",
        "--log",
        "-l",
        help="Investigation log file to read",
    ),
    last: int = typer.Option(10, "--last", "-n", help="Show last N investigations"),
    full: bool = typer.Option(False, "--full", "-f", help="Show full analysis (not just summary)"),
) -> None:
    """Show recent AI-powered investigations from watch mode.

    View investigation reports generated by --investigate mode.
    Useful for reviewing root cause analyses and remediation recommendations.
    """
    import json

    if not log_file.exists():
        console.print(f"[yellow]No investigations found at {log_file}[/yellow]")
        console.print("[dim]Start watching with: uatu watch --investigate[/dim]")
        return

    # Read investigations
    investigations_list = []
    try:
        with open(log_file) as f:
            for line in f:
                investigations_list.append(json.loads(line))
    except Exception as e:
        console.print(f"[red]Error reading log file: {e}[/red]")
        return

    if not investigations_list:
        console.print("[green]No investigations yet![/green]")
        return

    # Show last N investigations
    recent = investigations_list[-last:]

    for i, investigation in enumerate(recent):
        event = investigation["event"]
        system = investigation["system"]
        inv = investigation["investigation"]

        # Header
        timestamp = investigation["timestamp"].split("T")[1].split(".")[0]  # HH:MM:SS
        severity_color = {
            "info": "blue",
            "warning": "yellow",
            "error": "red",
            "critical": "red bold",
        }.get(event["severity"], "white")

        inv_num = len(investigations_list) - last + i + 1
        console.print(f"\n[{severity_color}]━━━ Investigation #{inv_num} [{timestamp}] ━━━[/{severity_color}]")
        console.print(f"[bold]{event['message']}[/bold]")
        console.print(f"[dim]Type: {event['type']} | Severity: {event['severity']}[/dim]")

        # System state
        console.print(
            f"[dim]System: CPU {system['cpu_percent']:.1f}%, "
            f"Mem {system['memory_percent']:.1f}%, "
            f"Load {system['load_1min']:.2f}[/dim]"
        )

        # Cache indicator
        if inv.get("cached"):
            console.print(f"[dim]Cached analysis (seen {inv.get('cache_count', 1)}x)[/dim]")

        # Analysis
        if full:
            # Full markdown analysis
            from uatu.chat import LeftAlignedMarkdown

            md = LeftAlignedMarkdown(inv["analysis"])
            console.print(Panel(md, border_style=severity_color))
        else:
            # Just first few lines as summary
            lines = inv["analysis"].split("\n")
            summary_lines = [line for line in lines[:5] if line.strip()]
            summary = "\n".join(summary_lines)
            console.print(f"[dim]{summary}...[/dim]")
            console.print("[dim italic]Use --full to see complete analysis[/dim italic]")

    # Summary
    console.print()
    console.print(f"[dim]Total investigations logged: {len(investigations_list)}[/dim]")
    console.print(f"[dim]Log file: {log_file}[/dim]")


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
    """Show recent anomalies detected by watch mode.

    View the event log to see what anomalies the watcher has detected
    over time. Useful for reviewing system behavior history.
    """
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
        severity_emoji = {"info": "[i]", "warning": "[!]", "critical": "[!!]"}.get(event["severity"], "")

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


if __name__ == "__main__":
    app()
