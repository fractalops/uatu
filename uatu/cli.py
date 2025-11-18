"""Command-line interface for Uatu."""

import asyncio
import sys

import typer
from rich.console import Console

from uatu.audit_cli import audit_command
from uatu.chat_session.session import ChatSession

app = typer.Typer(
    name="uatu",
    help="Uatu - The Watcher: Agentic system troubleshooting powered by Claude",
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
) -> None:
    """
    Start Uatu in interactive chat mode (default) or run a single query from stdin.

    Interactive mode lets you troubleshoot conversationally with Claude.

    Stdin mode (pipe input):
        echo "What's using port 8080?" | uatu
        cat error.log | uatu
    """
    # If a subcommand was invoked, let it handle execution
    if ctx.invoked_subcommand is not None:
        return

    # Check for stdin mode (pipe or redirect)
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            # Run one-shot query with stdin content
            try:
                session = ChatSession()
                asyncio.run(session.run_oneshot(stdin_content))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
                raise typer.Exit(1)
            return

    # Interactive mode
    try:
        session = ChatSession()
        session.run()
    except Exception as e:
        console.print(f"[red]Error starting chat: {e}[/red]")
        console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
        raise typer.Exit(1)


# Register subcommands
app.command(name="audit")(audit_command)


if __name__ == "__main__":
    app()
