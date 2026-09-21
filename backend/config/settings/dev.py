import os
from pathlib import Path

from dotenv import load_dotenv

# 先注入 .env 再 setdefault，否则空默认值会挡住 .env 中的真实配置
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

os.environ.setdefault("SYNTIME_SECRET_KEY", "dev-only-insecure-key")
os.environ.setdefault("SYNTIME_DB_PASSWORD", "")

from .base import *  # noqa: E402

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [*INSTALLED_APPS, "corsheaders"]  # noqa: F405

MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", *MIDDLEWARE]  # noqa: F405

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
