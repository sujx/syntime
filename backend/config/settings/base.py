import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 本地开发凭据（SYNTIME_SECRET_KEY / SYNTIME_DB_PASSWORD 等）注入自 backend/.env（不入库）
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["SYNTIME_SECRET_KEY"]

DEBUG = False

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "apps.billing.apps.BillingConfig",
    "apps.cost.apps.CostConfig",
    "apps.audit.apps.AuditConfig",
    "apps.assets.apps.AssetsConfig",
    "apps.events.apps.EventsConfig",
    "apps.core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SYNTIME_DB_NAME", "syntime_dev"),
        "USER": os.environ.get("SYNTIME_DB_USER", "syntime"),
        "PASSWORD": os.environ.get("SYNTIME_DB_PASSWORD", ""),
        "HOST": os.environ.get("SYNTIME_DB_HOST", "localhost"),
        "PORT": os.environ.get("SYNTIME_DB_PORT", "5432"),
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive": {"()": "common.log_filters.SensitiveDataFilter"},
    },
    "formatters": {
        "console": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["sensitive"],
            "formatter": "console",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "common.api.response.ResultEnvelopeRenderer",
        "rest_framework.renderers.JSONRenderer",
    ),
    "EXCEPTION_HANDLER": "common.api.response.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "common.api.pagination.ResultPaginator",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=2),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # 登出依赖黑名单（token_blacklist app）；轮换时旧 refresh 同步拉黑
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SynTime API",
    "DESCRIPTION": "与时偕行 · 多云成本管理平台",
    "VERSION": "0.1.0",
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "common.api.response.spectacular_envelope_hook",
    ],
}

# Celery：broker 走环境变量，开发期可临时换 PG broker，生产必须 Redis（HANDOFF §6）
CELERY_BROKER_URL = os.environ.get("SYNTIME_CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TIMEZONE = TIME_ZONE

# 每月 3 日 03:00 对上一账期全量重算（tasks.md 任务2-④；镜像 platform_setting
# sync_cron.reaggregate_monthly 默认 "0 3 3 * *"）。账单同步完成后的窗口聚合由同步任务链式触发。
CELERY_BEAT_SCHEDULE = {
    "reaggregate-previous-month": {
        "task": "cost.reaggregate_previous_month",
        "schedule": crontab(hour=3, minute=0, day_of_month=3),
    },
    # 平台自算检测：每小时一次（tasks.md 任务 8——域名到期 / 预算超支均为状态判断，
    # 无需高频扫描）；两类检测按业务键 dedup 去重，重复扫描幂等。
    "self-calc-detect": {
        "task": "events.self_calc_detect",
        "schedule": crontab(minute=0),
    },
}

# 任务互斥锁的 Redis 地址：缺省复用 broker（仅当 broker 是 Redis 时），否则本机 1 号库
SYNTIME_LOCK_REDIS_URL = os.environ.get("SYNTIME_LOCK_REDIS_URL", "")
