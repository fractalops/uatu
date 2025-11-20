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


def main_callback(ctx: typer.Context) -> None:
    """
    Main entry point that handles both interactive mode and stdin mode.
    """
    # If a subcommand was invoked, let it handle execution
    if ctx.invoked_subcommand is not None:
        return

    # Check for stdin mode (pipe or redirect)
    has_stdin = not sys.stdin.isatty()
    stdin_content = sys.stdin.read().strip() if has_stdin else None

    # Get any remaining arguments from sys.argv (after "uatu")
    # Skip argv[0] (script name) and argv[1:] are the actual args
    # Filter out known subcommands
    import sys as sys_module
    known_commands = ["audit"]
    prompt_parts = []
    skip_next = False
    for i, arg in enumerate(sys_module.argv[1:]):  # Skip program name
        if skip_next:
            skip_next = False
            continue
        if arg in known_commands:
            # This is a subcommand, not a prompt
            return
        # Skip option flags
        if arg.startswith("-"):
            continue
        prompt_parts.append(arg)

    prompt = " ".join(prompt_parts) if prompt_parts else None

    # Build the full prompt
    full_prompt = None
    if stdin_content and prompt:
        # Combine stdin data with prompt
        full_prompt = f"Here's the data:\n\n{stdin_content}\n\nTask: {prompt}"
    elif stdin_content:
        # Use stdin as the full prompt
        full_prompt = stdin_content
    elif prompt:
        # Use argument as the full prompt
        full_prompt = prompt

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
    # Check if we have stdin and extra arguments
    # If so, run stdin mode directly to bypass Typer's command checking
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            # Check if there are any non-option arguments (excluding known subcommands)
            known_commands = ["audit"]
            args = [arg for arg in sys.argv[1:] if not arg.startswith("-") and arg not in known_commands]

            if args:
                # We have a prompt - combine with stdin
                prompt = " ".join(args)
                full_prompt = f"Here's the data:\n\n{stdin_content}\n\nTask: {prompt}"
            else:
                # Just use stdin as the prompt
                full_prompt = stdin_content

            # Run one-shot mode directly
            try:
                session = ChatSession()
                asyncio.run(session.run_oneshot(full_prompt))
                sys.exit(0)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                console.print("[yellow]Make sure ANTHROPIC_API_KEY is set in .env[/yellow]")
                sys.exit(1)

    # No stdin with extra args - let Typer handle it normally
    app()


if __name__ == "__main__":
    cli_main()
