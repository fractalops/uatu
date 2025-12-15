"""Configuration management using pydantic-settings."""


from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_require_approval() -> bool:
    """Auto-detect approval requirement based on TTY presence."""
    return True


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic API
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key")

    # Agent Configuration
    uatu_model: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Claude model to use",
    )
    uatu_max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for agent responses",
    )
    uatu_max_turns: int = Field(
        default=20,
        description="Maximum turns per conversation",
    )
    uatu_max_budget_usd: float | None = Field(
        default=None,
        description="Optional max budget (USD) per session; None to disable",
    )
    uatu_temperature: float = Field(
        default=0.0,
        description="Temperature for agent responses (0.0 = deterministic)",
    )

    # Safety Settings
    uatu_read_only: bool = Field(
        default=True,
        description="If true, agent can only read system state, not modify it",
    )
    uatu_require_approval: bool = Field(
        default_factory=_default_require_approval,
        description="If true, require user approval before executing risky actions",
    )
    uatu_allow_network: bool = Field(
        default=False,
        description="If true, allow network commands (curl, wget, etc.) - NOT RECOMMENDED",
    )
    uatu_enable_telemetry: bool = Field(
        default=True,
        description="If true, emit opt-in local telemetry for sessions/turns/tools",
    )
    uatu_telemetry_path: str = Field(
        default="~/.uatu/telemetry.jsonl",
        description="Path for local JSONL telemetry when enabled",
    )
    uatu_max_background_jobs: int = Field(
        default=1,
        description="Max concurrent background Bash jobs",
    )
    uatu_background_queue_size: int = Field(
        default=1,
        description="Max queued background Bash jobs beyond the concurrent limit",
    )

    # UI Settings
    uatu_show_tool_previews: bool = Field(
        default=True,
        description="If true, show one-line previews of tool results in the UI",
    )
    uatu_show_stats: bool = Field(
        default=True,
        description="If true, show session statistics (tokens, cost) in corner display",
    )
    uatu_console_width: int | None = Field(
        default=80,
        description="Console width. 80=default, 0=full terminal, None=auto-detect, >0=specific width",
    )

    # Tool surface
    uatu_tools_mode: str = Field(
        default="default",
        description="Tool surface: default | minimal | none",
    )

    # Agent Configuration
    uatu_enable_subagents: bool = Field(
        default=True,
        description="If true, enable specialized diagnostic subagents (cpu, memory, network, io)",
    )

    # Skills (filesystem-based)
    uatu_enable_skills: bool = Field(
        default=False,
        description="If true, enable Claude Skills from filesystem",
    )
    uatu_setting_sources: list[str] | None = Field(
        default=None,
        description='Skill setting sources, e.g., ["user","project"]; defaults to both when skills enabled',
    )



def get_settings() -> Settings:
    """Get settings instance (lazy-loaded)."""
    return Settings()
