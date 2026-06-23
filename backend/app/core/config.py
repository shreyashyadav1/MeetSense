from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepgram_api_key: str = ""
    groq_api_key: str = ""
    database_url: str = ""
    redis_url: str = "redis://localhost:6379"

    class Config:
        env_file = ".env"


settings = Settings()
