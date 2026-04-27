from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str  # формат: postgresql+asyncpg://user:pass@host:5432/dbname
    GROQ_API_KEY: str = ""  # опционально — бот работает и без него

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
