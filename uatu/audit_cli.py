"""CLI commands for security audit logs."""

from pathlib import Path

import typer
from rich.console import Console

from uatu.audit import SecurityAuditor

console = Console()


def audit_command(
    log_file: Path = typer.Option(
        Path.home() / ".uatu" / "security.jsonl",
        "--log",
        "-l",
        help="Audit log file to read",
    ),
    last: int = typer.Option(100, "--last", "-n", help="Show last N events"),
    event_type: str = typer.Option(None, "--type", "-t", help="Filter by event type"),
    summary: bool = typer.Option(False, "--summary", "-s", help="Show security summary statistics"),
) -> None:
    """View security audit logs.

    Shows permission decisions, SSRF blocks, suspicious patterns, and other
    security events. Use this to review what commands and network requests
    have been approved or denied.

    Examples:
        # Show recent audit events
        uatu audit

        # Show summary statistics
        uatu audit --summary

        # Filter by event type
        uatu audit --type bash_command_approval

        # Show last 50 events
        uatu audit --last 50
    """
    auditor = SecurityAuditor()

    if not auditor.audit_file.exists():
        console.print(f"[yellow]No audit log found at {auditor.audit_file}[/yellow]")
        console.print("[dim]Security events will be logged here once you start using Uatu[/dim]")
        return

    # Show summary if requested
    if summary:
        _show_summary(auditor)
        return

    # Get events (filtered or all)
    if event_type:
        events_list = auditor.get_events_by_type(event_type, limit=last)
        if not events_list:
            console.print(f"[yellow]No events found with type: {event_type}[/yellow]")
            console.print(
                "[dim]Available types: bash_command_approval, bash_command_denied, "
                "network_access_approval, ssrf_blocked, etc.[/dim]"
            )
            return
    else:
        events_list = auditor.get_recent_events(limit=last)

    if not events_list:
        console.print("[green]No audit events yet![/green]")
        return

    # Display events
    _show_events(events_list, auditor)


def _show_summary(auditor: SecurityAuditor) -> None:
    """Display security summary statistics."""
    from uatu.ui.console import ConsoleRenderer

    stats = auditor.get_security_summary()

    console.print("\n[bold cyan]Security Summary[/bold cyan]")
    console.print(f"[dim]Based on last {stats['total_events']} events[/dim]\n")

    # Create minimal summary table
    renderer = ConsoleRenderer(console)
    table = renderer.create_minimal_table(title="Security Event Statistics")
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right", style="yellow")

    table.add_row("Bash Approvals", str(stats["bash_approvals"]))
    table.add_row("Bash Denials", str(stats["bash_denials"]))
    table.add_row("Network Approvals", str(stats["network_approvals"]))
    table.add_row("Network Denials", str(stats["network_denials"]))
    table.add_row("SSRF Blocks", str(stats["ssrf_blocks"]), style="red" if stats["ssrf_blocks"] > 0 else "")
    table.add_row(
        "Network Command Blocks",
        str(stats["network_command_blocks"]),
        style="yellow" if stats["network_command_blocks"] > 0 else "",
    )
    table.add_row(
        "Suspicious Patterns",
        str(stats["suspicious_patterns"]),
        style="red" if stats["suspicious_patterns"] > 0 else "",
    )

    console.print(table)
    console.print(f"\n[dim]Audit log: {auditor.audit_file}[/dim]")


def _show_events(events_list: list, auditor: SecurityAuditor) -> None:
    """Display audit events."""
    console.print("\n[bold cyan]Security Audit Log[/bold cyan]")
    console.print(f"[dim]Showing {len(events_list)} most recent events[/dim]\n")

    for event in events_list:
        event_type_display = event.get("event_type", "unknown")
        timestamp = event.get("timestamp", "").split("T")[1].split(".")[0] if "T" in event.get("timestamp", "") else ""

        # Color code by event type
        if "denied" in event_type_display or "blocked" in event_type_display:
            color = "red"
        elif "approval" in event_type_display and not event.get("approved", True):
            color = "yellow"
        elif "auto_approved" in event_type_display:
            color = "green"
        else:
            color = "blue"

        console.print(f"[{color}]{timestamp}[/{color}] [{color}]{event_type_display}[/{color}]")

        # Show event-specific details
        if "bash" in event_type_display:
            _show_bash_event(event)
        elif "network" in event_type_display or "ssrf" in event_type_display:
            _show_network_event(event)
        elif "suspicious" in event_type_display:
            _show_suspicious_event(event)

        console.print()

    console.print(f"[dim]Audit log: {auditor.audit_file}[/dim]")


def _show_bash_event(event: dict) -> None:
    """Show bash command event details."""
    command = event.get("command", "")
    desc = event.get("description", "")
    if desc:
        console.print(f"  [dim]{desc}[/dim]")
    console.print(f"  [dim]$ {command[:100]}{'...' if len(command) > 100 else ''}[/dim]")

    if event.get("reason"):
        console.print(f"  [yellow]Reason: {event['reason']}[/yellow]")
    if event.get("approved") is not None:
        status = "Approved" if event["approved"] else "Denied"
        console.print(f"  Status: {status}")
    if event.get("added_to_allowlist"):
        console.print("  [green]Added to allowlist[/green]")


def _show_network_event(event: dict) -> None:
    """Show network access event details."""
    url = event.get("url", "")
    domain = event.get("domain", "")
    tool = event.get("tool", "")

    if tool:
        console.print(f"  Tool: {tool}")
    if domain:
        console.print(f"  [dim]Domain: {domain}[/dim]")
    if url:
        console.print(f"  [dim]URL: {url[:80]}{'...' if len(url) > 80 else ''}[/dim]")

    if event.get("reason"):
        console.print(f"  [yellow]Reason: {event['reason']}[/yellow]")
    if event.get("approved") is not None:
        status = "Approved" if event["approved"] else "Denied"
        console.print(f"  Status: {status}")
    if event.get("added_to_allowlist"):
        console.print("  [green]Added to allowlist[/green]")


def _show_suspicious_event(event: dict) -> None:
    """Show suspicious pattern event details."""
    command = event.get("command", "")
    pattern = event.get("pattern", "")
    console.print(f"  [yellow]Pattern: {pattern}[/yellow]")
    console.print(f"  [dim]$ {command[:100]}{'...' if len(command) > 100 else ''}[/dim]")
