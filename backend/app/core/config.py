"""Application settings, loaded from environment variables and ``backend/.env``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

TranscriptionMode = Literal["deepgram", "mock"]

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    # docker compose (nginx on port 80)
    "http://localhost",
    "http://127.0.0.1",
    # Vite dev server and `vite preview`
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Production frontend
    "https://meet-sense.vercel.app",
)

_REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")

_ASYNCPG_SCHEME = "postgresql+asyncpg"
_POSTGRES_SCHEMES = frozenset(
    {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2", "postgresql+pg8000"}
)


def normalize_database_url(url: str) -> str:
    """Return ``url`` in the form SQLAlchemy's asyncpg dialect accepts.

    Hosting providers hand out URLs such as ``postgres://…?sslmode=require``.
    asyncpg needs the ``postgresql+asyncpg`` scheme and spells the TLS option
    ``ssl``; left as-is, those URLs fail to connect.
    """
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in _POSTGRES_SCHEMES:
        scheme = _ASYNCPG_SCHEME
    if scheme != _ASYNCPG_SCHEME:
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "ssl" for key, _ in query):
        query = [("ssl" if key == "sslmode" else key, value) for key, value in query]
    return urlunsplit(parts._replace(scheme=scheme, query=urlencode(query)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # --- Live transcription ---------------------------------------------
    deepgram_api_key: str = ""
    # Unset (or blank) means "mock when DEEPGRAM_API_KEY is empty".
    mock_transcription: bool | None = None
    session_max_seconds: float = Field(default=1800, gt=0)
    ws_max_connections_per_ip: int = Field(default=3, ge=1)

    # --- AI insights ------------------------------------------------------
    groq_api_key: str = ""
    # Groq retires models over time (https://console.groq.com/docs/deprecations);
    # override GROQ_MODEL instead of editing code.
    groq_model: str = "openai/gpt-oss-120b"
    # reasoning_effort for reasoning models such as gpt-oss; blank for models without it.
    groq_reasoning_effort: Literal["low", "medium", "high", ""] = "low"
    groq_temperature: float = Field(default=0.3, ge=0, le=2)
    # Includes the reasoning tokens gpt-oss spends before it answers.
    groq_max_tokens: int = Field(default=4096, gt=0)
    groq_timeout_seconds: float = Field(default=30, gt=0)
    # Longer transcripts are shortened (start and end kept) before prompting.
    ai_max_transcript_chars: int = Field(default=32_000, ge=1_000)

    # --- GitHub Issues export -----------------------------------------------
    # Export is enabled only when all three are set. The token needs Issues
    # read/write on the one repository; callers must send GITHUB_EXPORT_KEY.
    github_token: str = ""
    github_repository: str = ""
    github_export_key: str = ""
    github_issue_label: str = Field(default="meetsense", min_length=1, max_length=50)
    github_api_url: str = "https://api.github.com"
    github_timeout_seconds: float = Field(default=15, gt=0)

    # --- Persistence ------------------------------------------------------
    database_url: str = ""
    # Required behind transaction-mode poolers (PgBouncer, Supabase :6543).
    db_disable_statement_cache: bool = False
    # When PostgreSQL is unreachable, serve from memory (true) or fail with 503 (false).
    allow_memory_fallback: bool = True
    # Blank disables Redis; live transcripts are then fanned out in-process only.
    redis_url: str = "redis://localhost:6379"

    # --- HTTP ---------------------------------------------------------------
    # Comma-separated. Applies to CORS and to the WebSocket Origin check.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS)
    )
    # Proxies whose X-Forwarded-For header is trusted for the client IP (rate
    # limits, per-IP socket caps). The backend runs behind Railway's edge or
    # nginx; restrict this to the proxy's address if uvicorn is ever exposed
    # directly, or clients can spoof their IP.
    forwarded_allow_ips: str = "*"
    port: int = 8000

    @field_validator("mock_transcription", mode="before")
    @classmethod
    def _blank_means_auto(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            if not value.strip():
                return list(DEFAULT_ALLOWED_ORIGINS)
            value = value.split(",")
        if isinstance(value, list | tuple):
            return [str(item).strip().rstrip("/") for item in value if str(item).strip()]
        return value

    @field_validator("github_repository")
    @classmethod
    def _check_repository(cls, value: str) -> str:
        value = value.strip()
        if value and not _REPOSITORY.fullmatch(value):
            raise ValueError("GITHUB_REPOSITORY must look like owner/name")
        return value

    @field_validator("github_api_url")
    @classmethod
    def _strip_api_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @property
    def transcription_mode(self) -> TranscriptionMode:
        if self.mock_transcription is None:
            return "deepgram" if self.deepgram_api_key else "mock"
        return "mock" if self.mock_transcription else "deepgram"

    @property
    def ai_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def github_export_configured(self) -> bool:
        return bool(self.github_token and self.github_repository and self.github_export_key)


settings = Settings()
