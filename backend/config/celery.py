"""Celery 应用入口（platform.md 9.1：Celery + Redis 承担四类任务与 T+1 调度）。

broker 一律走环境变量（HANDOFF §6：开发期可临时用 PG 作 broker，
生产必须 Redis，故不得写死）。
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("syntime")

# 配置键带 CELERY_ 前缀映射到 celery 原生配置（如 CELERY_BROKER_URL → broker_url）
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
