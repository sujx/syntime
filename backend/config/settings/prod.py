import os

from .base import *  # noqa: F403

ALLOWED_HOSTS = [h for h in os.environ.get("SYNTIME_ALLOWED_HOSTS", "").split(",") if h]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("SYNTIME_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ── 同源托管前端：本机部署拍板「gunicorn + WhiteNoise，不装 nginx」（2026-11-18）。
# 前端由 vite 以默认 base "/" 构建，整棵 dist/ 挂到站点根；站点根与 /cost 这类深链由
# SPA_INDEX 兜住（视图见 config/spa.py，挂载条件见 config/urls.py）。dev/test 不设这两项，
# 仍走 vite 自己的 5173 与 /api 代理，行为不变。
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]

SPA_ROOT = (BASE_DIR.parent / "frontend" / "dist").resolve()  # noqa: F405
WHITENOISE_ROOT = SPA_ROOT
SPA_INDEX = SPA_ROOT / "index.html"
