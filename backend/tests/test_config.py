import pytest

from app.core.config import DEFAULT_ALLOWED_ORIGINS, Settings, normalize_database_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@db:5432/app", "postgresql+asyncpg://u:p@db:5432/app"),
        ("postgresql://u:p@db/app", "postgresql+asyncpg://u:p@db/app"),
        ("postgresql+psycopg2://u:p@db/app", "postgresql+asyncpg://u:p@db/app"),
        ("postgresql+asyncpg://u:p@db/app", "postgresql+asyncpg://u:p@db/app"),
        (
            "postgres://u:p%40ss@db/app?sslmode=require",
            "postgresql+asyncpg://u:p%40ss@db/app?ssl=require",
        ),
        ("  postgresql://u:p@db/app  ", "postgresql+asyncpg://u:p@db/app"),
        ("", ""),
        ("sqlite+aiosqlite:///local.db", "sqlite+aiosqlite:///local.db"),
    ],
)
def test_normalize_database_url(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected


def test_explicit_ssl_parameter_wins_over_sslmode() -> None:
    url = "postgresql://u:p@db/app?ssl=verify-full&sslmode=disable"
    assert (
        normalize_database_url(url)
        == "postgresql+asyncpg://u:p@db/app?ssl=verify-full&sslmode=disable"
    )


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("DEEPGRAM_API_KEY", "MOCK_TRANSCRIPTION", "ALLOWED_ORIGINS", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_database_url_from_env_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _settings(monkeypatch, DATABASE_URL="postgres://u:p@db/app")
    assert config.database_url == "postgresql+asyncpg://u:p@db/app"


def test_allowed_origins_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _settings(
        monkeypatch, ALLOWED_ORIGINS=" https://a.example/ , http://localhost:5173,, "
    )
    assert config.allowed_origins == ["https://a.example", "http://localhost:5173"]


def test_blank_allowed_origins_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(monkeypatch, ALLOWED_ORIGINS="").allowed_origins == list(
        DEFAULT_ALLOWED_ORIGINS
    )


@pytest.mark.parametrize(
    ("env", "mode"),
    [
        ({}, "mock"),
        ({"MOCK_TRANSCRIPTION": ""}, "mock"),
        ({"DEEPGRAM_API_KEY": "key"}, "deepgram"),
        ({"DEEPGRAM_API_KEY": "key", "MOCK_TRANSCRIPTION": "true"}, "mock"),
        ({"MOCK_TRANSCRIPTION": "false"}, "deepgram"),
    ],
)
def test_transcription_mode(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], mode: str
) -> None:
    assert _settings(monkeypatch, **env).transcription_mode == mode
