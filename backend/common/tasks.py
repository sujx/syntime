"""Celery 任务公共基类（engineering-conventions §5.1）。

互斥锁（Redis SET NX EX）、指数退避重试（autoretry_for）、audit_log 任务钩子
三件事收口在 ``SynTimeTask``，任务实现不得各自重写（PRD 4.4-4、tasks.md 各任务互斥要求）。

用法::

    @app.task(base=SynTimeTask, bind=True)
    def sync_bills(self, account_id: int) -> None:
        ...

    锁粒度默认为任务名；按账号等维度互斥的任务覆写 ``get_lock_key``。
    重试参数（autoretry_for / max_retries / retry_backoff）为类属性默认值，
    子任务可按 tasks.md 各自约定覆写，但不得绕过基类自建锁或重试。

锁地址解析顺序：SYNTIME_LOCK_REDIS_URL → broker URL（仅 Redis 协议时）→ 本机 1 号库。
"""

import logging
import secrets
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import redis
from celery import Task
from celery.exceptions import Ignore
from django.conf import settings

from common.audit import record_audit

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "syntime:mutex"
# 只删自己持有的锁：值比对通过才删除，防止误删他人过期后重建的锁
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


def get_lock_client() -> redis.Redis:
    """返回互斥锁用的 Redis 客户端（按地址缓存）。"""
    url = settings.SYNTIME_LOCK_REDIS_URL
    if not url:
        broker = getattr(settings, "CELERY_BROKER_URL", "")
        url = broker if broker.startswith("redis") else "redis://localhost:6379/1"
    return _client_from_url(url)


@lru_cache(maxsize=4)
def _client_from_url(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)


def acquire_mutex(client: redis.Redis, key: str, ttl_seconds: int) -> str | None:
    """尝试获取互斥锁；成功返回持有令牌，锁已被占返回 None（SET NX EX）。"""
    token = secrets.token_hex(16)
    ok = client.set(f"{_LOCK_PREFIX}:{key}", token, nx=True, ex=ttl_seconds)
    return token if ok else None


def release_mutex(client: redis.Redis, key: str, token: str) -> None:
    """释放互斥锁（Lua 比对令牌后删除）。"""
    client.eval(_RELEASE_LUA, 1, f"{_LOCK_PREFIX}:{key}", token)


class SynTimeTask(Task):
    """互斥 + 退避重试 + 审计钩子的公共任务基类。"""

    abstract = True

    # tasks.md 任务 1：失败按 3 次指数退避重试；子类按需收窄 autoretry_for
    autoretry_for: tuple[type[BaseException], ...] = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3

    # 互斥锁 TTL：需大于任务最长执行时间（资产同步单账号 ≤5 分钟），防止孤儿锁长期占位
    mutex_ttl = 3600
    # audit_log.action 取值须在 AuditLog.Action 枚举内（sync/aggregate/export/budget_import/query）
    audit_action = "sync"

    def get_lock_key(self, args: Sequence[Any], kwargs: dict[str, Any]) -> str | None:
        """返回互斥锁键；None 表示该任务不互斥。默认按任务名。"""
        return self.name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        lock_key = self.get_lock_key(args, kwargs)
        if lock_key is None:
            return super().__call__(*args, **kwargs)

        client = get_lock_client()
        token = acquire_mutex(client, lock_key, self.mutex_ttl)
        if token is None:
            logger.warning("任务互斥跳过 task=%s lock=%s", self.name, lock_key)
            record_audit(
                self.audit_action,
                operator=self._audit_operator(kwargs),
                params={"task": self.name, "lock": lock_key, "reason": "mutex_busy"},
                result="skipped",
            )
            raise Ignore()

        try:
            return super().__call__(*args, **kwargs)
        finally:
            release_mutex(client, lock_key, token)

    def on_success(self, retval: Any, task_id: str, args: Any, kwargs: Any) -> None:
        record_audit(
            self.audit_action,
            operator=self._audit_operator(kwargs),
            params={"task": self.name, "args": args, "kwargs": kwargs},
            result="success",
        )

    def on_failure(
        self, exc: BaseException, task_id: str, args: Any, kwargs: Any, einfo: Any
    ) -> None:
        record_audit(
            self.audit_action,
            operator=self._audit_operator(kwargs),
            params={
                "task": self.name,
                "args": args,
                "kwargs": kwargs,
                "error": str(exc)[:500],
            },
            result="failed",
        )

    @staticmethod
    def _audit_operator(kwargs: Any) -> str | None:
        """手动触发的任务可携带 operator（用户名）；系统调度任务为 None。"""
        if isinstance(kwargs, dict):
            operator = kwargs.get("operator")
            if isinstance(operator, str) and operator:
                return operator
        return None
