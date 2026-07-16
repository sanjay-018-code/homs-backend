import os
import sys
from pydantic_settings import BaseSettings

_SECRET_KEY = os.getenv("SECRET_KEY")
if not _SECRET_KEY:
    sys.exit(
        "FATAL: SECRET_KEY environment variable is not set. "
        "Refusing to start with a default/hardcoded signing key. "
        "Set SECRET_KEY in your environment or .env file (see .env.example)."
    )

class Settings(BaseSettings):
    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017/homs")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "homs")
    SECRET_KEY: str = _SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # SMTP Configuration for Nodemailer-like alerts
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")  # Secure Google App Password
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "homs-alerts@college.edu")

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
