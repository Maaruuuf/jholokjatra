"""Central settings, loaded from environment variables / .env (pydantic-settings)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM providers
    groq_api_key: str = ""
    gemini_api_key: str = ""
    llm_provider_order: str = "groq,gemini,ollama"
    groq_model_small: str = "openai/gpt-oss-20b"
    groq_model_large: str = "openai/gpt-oss-120b"
    gemini_model_small: str = "gemini-2.5-flash-lite"
    gemini_model_large: str = "gemini-2.5-flash"
    ollama_enabled: bool = False
    ollama_host: str = "http://localhost:11434"
    ollama_model_small: str = "qwen2.5:3b"
    ollama_model_large: str = "qwen2.5:7b"
    llm_max_tokens_per_plan: int = 12000  # reasoning models spend tokens thinking
    groq_reasoning_effort: str = "low"  # low | medium | high (gpt-oss models only)
    use_chroma: bool = False  # opt-in: Chroma downloads an ~80 MB embedding model on first use

    # HTTP / app
    http_user_agent: str = "JholokJatra/0.1 (student project)"
    http_timeout_s: float = 15.0
    http_retries: int = 3
    data_dir: Path = Path("data")
    log_level: str = "INFO"

    # cache TTLs (seconds)
    ttl_forecast: int = 3600
    ttl_alerts: int = 3600
    ttl_quakes: int = 900
    ttl_static: int = 7 * 24 * 3600

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jholokjatra.db"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def provider_order(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_provider_order.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
