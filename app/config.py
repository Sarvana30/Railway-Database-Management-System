"""Application settings, loaded from environment variables / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "mysql+pymysql://railway:railway@localhost:3306/railway"
    )
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "dev-secret-change-me")
    HOLD_DURATION_MINUTES: int = int(os.getenv("HOLD_DURATION_MINUTES", "5"))
    MIN_LAYOVER_MINUTES: int = int(os.getenv("MIN_LAYOVER_MINUTES", "30"))


settings = Settings()
