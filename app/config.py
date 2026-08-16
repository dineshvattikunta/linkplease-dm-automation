import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Mock API credentials (read strictly from environment variable API_KEY)
    API_KEY: str = ""
    PSEUDOGRAM_BASE_URL: str = "https://pseudogram-api.onrender.com"

    # Profile & Submission info
    USER_NAME: str = "Vattikunta Dinesh Chowdary"
    USER_EMAIL: str = "vattikuntad@gmail.com"
    USER_PHONE: str = "+91 7989853264"
    USER_WHATSAPP: str = "+91 7989853264"
    USER_LINKEDIN: str = "https://www.linkedin.com/in/dinesh-vattikunta"
    GITHUB_REPO_URL: str = "https://github.com/dineshvattikunta/linkplease-dm-automation"
    WORKING_URL: str = "https://linkplease-dm-automation.onrender.com"
    LOOM_URL: str = "https://loom.com/share/placeholder"

    # App & Database Settings
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DATABASE_URL: str = "sqlite+aiosqlite:///./linkplease.db"

    # Rate Limiter Controls
    # Strict limit: Max 9 requests per 60s window (Mock API limit is 10/60s)
    RATE_LIMIT_MAX_REQUESTS: int = 9
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Worker Settings
    WORKER_POLL_INTERVAL_SECONDS: float = 0.5
    MAX_RETRY_ATTEMPTS: int = 5
    RECONCILER_INTERVAL_SECONDS: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
