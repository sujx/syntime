import os

from .base import *  # noqa: F403

ALLOWED_HOSTS = [h for h in os.environ.get("SYNTIME_ALLOWED_HOSTS", "").split(",") if h]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("SYNTIME_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
