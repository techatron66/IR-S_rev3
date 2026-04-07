from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # NV API
    NV_API_KEY: str = "nvapi-placeholder"
    NV_API_BASE: str = "https://integrate.api.nvidia.com/v1"
    KIMI_MODEL: str = "moonshotai/kimi-k2-5"
    VISION_MODEL: str = "meta/llama-3.2-90b-vision-instruct"

    # Auth
    STUDENT_JWT_SECRET: str = "change-me-in-production"
    STUDENT_JWT_ALGO: str = "HS256"
    STUDENT_JWT_EXPIRE_HOURS: int = 24

    # Ports
    IRIS_HOST: str = "0.0.0.0"
    PROF_DASH_PORT: int = 8000
    AI_ENGINE_PORT: int = 8001
    STUDENT_APP_PORT: int = 8002
    GRADING_ENGINE_PORT: int = 8003
    STUDENT_PORTAL_PORT: int = 8004

    # Internal auth
    INTERNAL_KEY: str = "iris-internal-secret"

    # OCR
    OCR_HANDWRITING_THRESHOLD: int = 50
    TESSERACT_CMD: str = "tesseract"  # Windows: use just 'tesseract' or full path

    # Limits
    MAX_CONCURRENT_NV_CALLS: int = 5
    GRADING_RETRY_ATTEMPTS: int = 3
    MAX_UPLOAD_SIZE_MB: int = 50
    SHEET_RETENTION_DAYS: int = 90

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
