"""Command-line interface for Uatu."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from uatu.agent import UatuAgent
from uatu.chat import UatuChat
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

            # Format tool call like Claude Code
            if tool_name == "Bash":
                cmd = tool_input.get("command", "")
                desc = tool_input.get("description", "")
                console.print(f"[dim]> {desc or cmd}[/dim]")
            else:
                console.print(f"[dim]> Using tool: {tool_name}[/dim]")

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
        if hasattr(element, "justify"):
            element.justify = "left"

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
    """
    Show recent anomalies detected by watch mode.

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
