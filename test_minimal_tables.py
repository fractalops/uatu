#!/usr/bin/env python3
"""Demo comparing standard Rich tables vs minimal tables."""

from rich.console import Console
from rich.table import Table

# Import Uatu's console renderer
from uatu.ui.console import ConsoleRenderer


def demo_standard_table():
    """Show standard Rich table with borders."""
    console = Console()

    console.print("\n[bold yellow]Standard Rich Table (with borders)[/bold yellow]\n")

    table = Table(title="Allowlisted Commands", border_style="cyan")
    table.add_column("Pattern", style="green")
    table.add_column("Type", style="dim")
    table.add_column("Added", style="dim")

    table.add_row("ps", "base_command", "2025-01-15 10:30")
    table.add_row("df -h", "exact", "2025-01-15 10:31")
    table.add_row("top -l 1", "exact", "2025-01-15 10:32")
    table.add_row("netstat -an", "exact", "2025-01-15 10:33")
    table.add_row("lsof", "base_command", "2025-01-15 10:34")

    console.print(table)


def demo_minimal_table():
    """Show minimal table without borders."""
    console = Console()

    console.print("\n[bold cyan]Minimal Table (no borders, clean)[/bold cyan]\n")

    renderer = ConsoleRenderer(console)
    table = renderer.create_minimal_table(title="Allowlisted Commands")
    table.add_column("Pattern", style="green")
    table.add_column("Type", style="dim")
    table.add_column("Added", style="dim")

    table.add_row("ps", "base_command", "2025-01-15 10:30")
    table.add_row("df -h", "exact", "2025-01-15 10:31")
    table.add_row("top -l 1", "exact", "2025-01-15 10:32")
    table.add_row("netstat -an", "exact", "2025-01-15 10:33")
    table.add_row("lsof", "base_command", "2025-01-15 10:34")

    console.print(table)


def demo_process_list():
    """Show process list in minimal table."""
    console = Console()

    console.print("\n[bold cyan]Process List (minimal table)[/bold cyan]\n")

    renderer = ConsoleRenderer(console)
    table = renderer.create_minimal_table(title="High Memory Processes")
    table.add_column("PID", style="cyan", no_wrap=True)
    table.add_column("Memory", justify="right", style="yellow")
    table.add_column("CPU", justify="right", style="green")
    table.add_column("Command", style="dim")

    table.add_row("1234", "2.3 GB", "87%", "python app.py")
    table.add_row("5678", "1.8 GB", "45%", "node server.js")
    table.add_row("9012", "890 MB", "12%", "nginx: worker")
    table.add_row("3456", "650 MB", "8%", "postgres: checkpointer")
    table.add_row("7890", "420 MB", "3%", "redis-server")

    console.print(table)


def demo_audit_summary():
    """Show audit summary in minimal table."""
    console = Console()

    console.print("\n[bold cyan]Security Event Statistics (minimal)[/bold cyan]\n")

    renderer = ConsoleRenderer(console)
    table = renderer.create_minimal_table(title="Security Event Statistics")
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right", style="yellow")

    table.add_row("Bash Approvals", "23")
    table.add_row("Bash Denials", "5", style="red")
    table.add_row("Network Approvals", "12")
    table.add_row("Network Denials", "2")
    table.add_row("SSRF Blocks", "0")
    table.add_row("Network Command Blocks", "3", style="yellow")
    table.add_row("Suspicious Patterns", "1", style="red")

    console.print(table)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Comparing Table Styles in Uatu")
    print("="*60)

    demo_standard_table()
    print("\n" + "-"*60)

    demo_minimal_table()
    print("\n" + "-"*60)

    demo_process_list()
    print("\n" + "-"*60)

    demo_audit_summary()
    print("\n" + "="*60)
    print("✓ Minimal tables are cleaner and more scannable!")
    print("="*60 + "\n")
