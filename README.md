# Uatu

AI-powered system troubleshooting agent using Claude.

<img src="uatu_.gif" alt="autu-demo" width="2000"/>

**What it does:**
- Chat with your system to diagnose issues
- Pipe logs directly for instant analysis
- Approve commands before execution with granular controls
- Connects symptoms across CPU, memory, network, and processes

**Platforms:**
- macOS
- Linux

## Installation

### Using pipx (recommended)

```bash
# Install with pipx for isolated environment
pipx install uatu

# Configure API key
echo "ANTHROPIC_API_KEY=your_key" > .env
```

### Using pip

```bash
# Install globally or in a virtual environment
pip install uatu

# Configure API key
echo "ANTHROPIC_API_KEY=your_key" > .env
```

### From source with uv

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/fractalops/uatu.git
cd uatu
uv sync

# Configure API key
echo "ANTHROPIC_API_KEY=your_key" > .env
```

## Quick Start

### Interactive Chat

Start a troubleshooting session:

```bash
# Read-only mode (default) - uses MCP tools, no bash
uatu

# Allow bash commands with approval prompts
UATU_READ_ONLY=false uatu
```

Example questions:
- "What's causing high CPU usage?"
- "Why is my server running slowly?"
- "Investigate recent memory issues"
- "What's listening on port 8080?"

Commands require approval unless allowlisted.

### Stdin Mode

Pipe data for analysis:

```bash
# Read-only (default) - MCP tools only
cat /var/log/app.log | uatu "find errors"

# Enable bash commands (requires UATU_READ_ONLY=false)
UATU_READ_ONLY=false journalctl -u myservice | uatu "why did this crash?"

# Safe bash commands (ps, df, top, etc.) auto-approve from allowlist
UATU_READ_ONLY=false ps aux | uatu "diagnose memory issues"
```

Allowlisted commands auto-approve in stdin mode. TTY required for interactive approval prompts.


## Configuration

Create `.env`:

```env
# Required
ANTHROPIC_API_KEY=your_key

# Security (defaults shown)
UATU_READ_ONLY=true                     # true: MCP tools only, false: allow bash
UATU_REQUIRE_APPROVAL=true              # Require approval before bash execution
UATU_ALLOW_NETWORK=false                # Allow network access (WebFetch, WebSearch)

# Optional
UATU_MODEL=claude-sonnet-4-5-20250929  # Claude model
UATU_CONSOLE_WIDTH=80                   # Terminal width (80, 0=full, None=auto)
UATU_ENABLE_SUBAGENTS=true              # Specialized diagnostic agents
UATU_SHOW_TOOL_PREVIEWS=true            # Show tool result previews
UATU_SHOW_STATS=true                    # Show session token/cost stats
```

## Security

### Command Approval

Bash commands require approval unless allowlisted:

```bash
⚠ Bash command approval required
Risk: Credential Access

⚠ Warning: This command may access SSH keys, certificates, or other credentials

ls -la ~/.ssh/

  ○ Allow once
  ○ Always allow (exact)
  → Deny
```

### Audit Log

Security decisions are logged to `~/.config/uatu/audit.jsonl`:

```bash
# View audit log (last 100 events)
uatu audit

# View recent events
uatu audit --last 20

# View specific event types
uatu audit --type bash_command_approval

# View summary statistics
uatu audit --summary
```

### Allowlist

Manage approved commands in `~/.config/uatu/allowlist.json`:

```bash
# View directly
cat ~/.config/uatu/allowlist.json

# In interactive chat (with tab completion)
/allowlist                    # Show approved commands
/allowlist add <command>      # Add to allowlist
/allowlist remove <pattern>   # Remove from allowlist
/allowlist clear              # Clear all
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Built With
- [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Rich](https://github.com/Textualize/rich) - Terminal formatting
- [Typer](https://github.com/fastapi/typer) - CLI framework
- [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) - Interactive input
