"""Configuration management using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic API
    anthropic_api_key: str = Field(..., description="Anthropic API key")

    # Agent Configuration
    uatu_model: str = Field(
        default="claude-sonnet-4-5-20250929",
        description="Claude model to use",
    )
    uatu_max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for agent responses",
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
        default=True,
        description="If true, require user approval before executing risky actions",
    )


def get_settings() -> Settings:
    """Get settings instance (lazy-loaded)."""
    return Settings()
