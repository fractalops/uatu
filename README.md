# Uatu

Your AI partner for system operations and troubleshooting.

<img src="uatu.gif" alt="autu-demo" width="2000"/>


**Core capabilities:**
- Interactive chat: Conversational troubleshooting with your system
- Stdin mode: Pipe logs and data for instant AI analysis
- Security-first: Granular command approval and allowlist system
- Intelligent analysis: Connect CPU spikes, memory leaks, and process behavior

**Tested on Platforms:**
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

### Interactive Chat Mode (Default)

Start a conversational troubleshooting session:

```bash
# Default mode
uatu

# Allow bash commands with approval prompts
UATU_READ_ONLY=false uatu
```

Ask questions naturally and get AI-powered system analysis:
- "What's causing high CPU usage?"
- "Why is my server running slowly?"
- "Investigate recent memory issues"
- "What's listening on port 8080?"

**Security**: Bash commands require user approval. Use `UATU_READ_ONLY=true` for read-only mode (MCP tools only).

### Stdin Mode (One-Shot Analysis)

Pipe system data directly for instant troubleshooting:

```bash
# Analyze application logs
cat /var/log/app.log | uatu "find errors and suggest fixes"

# Investigate crashed process
journalctl -u myservice --since "1 hour ago" | uatu "why did this crash?"

# Debug high memory usage
ps aux --sort=-%mem | head -20 | uatu "diagnose memory issues"

# Network troubleshooting
netstat -tulpn | uatu "find port conflicts"
```

**For automated monitoring/scripts:**

```bash
# Read-only mode (safest for automation)
UATU_READ_ONLY=true tail -100 /var/log/syslog | uatu "check for issues"

# Trust allowlist (requires pre-approved commands)
UATU_REQUIRE_APPROVAL=false dmesg | uatu "check hardware errors"
```

**Workflow for scripts:**
1. Run `uatu` interactively first
2. Approve diagnostic commands with "Always allow"
3. Use `UATU_REQUIRE_APPROVAL=false` in scripts to trust allowlist


## Configuration

Create `.env` with options:

```env
# Required
ANTHROPIC_API_KEY=your_key

# Optional
UATU_MODEL=claude-sonnet-4-5-20250929  # Claude model to use
UATU_READ_ONLY=true                     # Agent can only read, not modify system
UATU_REQUIRE_APPROVAL=true              # Require approval for risky actions
UATU_ALLOW_NETWORK=false                # Block network commands (curl, wget, etc.)
```

## Security Features

### Command Approval System

All bash commands require approval unless allowlisted:

```bash
⚠ Bash command approval required
Risk: Credential Access

⚠ Warning: This command may access SSH keys, certificates, or other credentials

ls -la ~/.ssh/

  ○ Allow once
  ○ Always allow (exact)
  → Deny
```

### Audit Logging

All security decisions are logged:

```bash
# View audit log
uatu audit show

# View recent events
uatu audit show --last 20

# View specific event types
uatu audit show --type bash_approval
```

### Allowlist Management

View and manage approved commands:

```bash
# View allowlist
cat ~/.config/uatu/allowlist.json

# Interactive chat commands (with tab completion)
/allowlist                              # Show approved commands
/allowlist add <command>                # Add command to allowlist
/allowlist remove <pattern>             # Remove pattern from allowlist
/allowlist clear                        # Clear all entries
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

## Acknowledgments
- [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python) for building the agent.
- [Typer](https://github.com/fastapi/typer) for the terminal UI
- [Rich](https://github.com/Textualize/rich) for formatting text in the terminal.
