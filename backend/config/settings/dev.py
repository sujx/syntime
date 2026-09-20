import os

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
