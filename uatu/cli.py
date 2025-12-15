"""Command-line interface for Uatu."""

import asyncio
import sys

import typer
from rich.console import Console

from uatu.audit_cli import audit_command
from uatu.chat_session.session import ChatSession

app = typer.Typer(
    name="uatu",
    help="Uatu: Your Interactive System Troubleshooting Assistant",
    add_completion=False,
)
console = Console()


def _build_full_prompt(stdin_content: str | None, argv_args: list[str], known_commands: list[str]) -> str | None:
    """Normalize stdin/argv into a single prompt string."""
    prompt_parts: list[str] = []
    for arg in argv_args:
        if arg in known_commands:
            return None  # subcommand flow should be handled by Typer
        if arg.startswith("-"):
            continue
        prompt_parts.append(arg)

    prompt = " ".join(prompt_parts) if prompt_parts else None

    if stdin_content and prompt:
        return f"Here's the data:\n\n{stdin_content}\n\nTask: {prompt}"
    if stdin_content:
        return stdin_content
    if prompt:
        return prompt
    return None


def main_callback(ctx: typer.Context) -> None:
    """
    Main entry point that handles both interactive mode and stdin mode.
    """
    # If a subcommand was invoked, let it handle execution
    if ctx.invoked_subcommand is not None:
        return

    known_commands = ["audit"]
    argv_args = sys.argv[1:]
    full_prompt = _build_full_prompt(stdin_content=None, argv_args=argv_args, known_commands=known_commands)

    # Run one-shot mode if we have a prompt
    if full_prompt:
        try:
            session = ChatSession()
            asyncio.run(session.run_oneshot(full_prompt))
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
            raise typer.Exit(1)
        return

    # Interactive mode (no stdin, no prompt)
    try:
        session = ChatSession()
        session.run()
    except Exception as e:
        console.print(f"[red]Error starting chat: {e}[/red]")
        console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
        raise typer.Exit(1)

app.callback(invoke_without_command=True)(main_callback)


# Register subcommands
app.command(name="audit")(audit_command)


def cli_main():
    """Main CLI entry point with preprocessing for stdin mode."""
    known_commands = ["audit"]

    # If stdin is provided, handle one-shot mode directly and skip Typer parsing
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        full_prompt = _build_full_prompt(stdin_content or None, sys.argv[1:], known_commands)

        if full_prompt:
            try:
                session = ChatSession()
                asyncio.run(session.run_oneshot(full_prompt))
                sys.exit(0)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
                sys.exit(1)

    # No stdin (or empty) - let Typer handle interactive/subcommand flow
    app()


if __name__ == "__main__":
    cli_main()
