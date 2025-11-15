# Uatu

Your AI partner for system operations—from guided troubleshooting to autonomous problem-solving.

<img src="uatu.gif" alt="autu-demo" width="2000"/>


**Core capabilities:**
- Chat with your system: Ask questions and get AI-powered analysis
- One-shot investigations: Instant diagnosis for specific issues
- Autonomous monitoring: Learn baselines and detect anomalies
- Intelligent analysis: Connect CPU spikes, memory leaks, and process behavior
- Cost-efficient: Prompt caching and smart rate limiting

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
# Default (read-only, requires approval for bash commands)
uv run uatu

# Allow bash commands with approval prompts
UATU_READ_ONLY=false uv run uatu
```

Ask questions naturally and get AI-powered analysis:
- "What's causing high CPU usage?"
- "Why is my server running slowly?"
- "Investigate recent memory issues"
- "Check for network bottlenecks"

**Security**: By default, bash commands require user approval. Set `UATU_READ_ONLY=false` in `.env` to enable bash (with approval prompts).

### One-Shot Investigation

Investigate a specific symptom immediately:

```bash
uv run uatu investigate "server running slowly"
uv run uatu investigate "high CPU usage"
uv run uatu investigate "memory leak suspected"
```

The agent will:
- Gather relevant system information using bash commands
- Analyze patterns and correlate signals
- Provide root cause analysis
- Suggest actionable remediation steps

**Best for**: Quick diagnostics, automation, scripting

### Continuous Monitoring

Watch your system and detect anomalies autonomously:

```bash
# Fast testing (1 minute baseline)
uv run uatu watch --baseline 1

# Production monitoring (5 minute baseline, default)
uv run uatu watch

# With AI investigation of detected anomalies
uv run uatu watch --investigate
```


## Configuration

Create `.env` with options:

```env
# Required
ANTHROPIC_API_KEY=your_key

# Optional
UATU_MODEL=claude-sonnet-4-5-20250929  # Claude model to use
UATU_READ_ONLY=true                     # Agent can only read, not modify system
UATU_REQUIRE_APPROVAL=true              # Require approval for risky actions
```

## Development

```bash
# Run tests (20 unit tests)
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
- [Riche](https://github.com/Textualize/rich) for formatting text in the terminal.
