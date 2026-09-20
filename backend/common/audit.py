"""audit_log 写入收口（engineering-conventions §2：审计装饰器与 Celery 任务钩子的公共底座）。

写入失败只记日志、绝不打断业务流（审计是旁路，不能反过来拖垮任务）。
参数快照做长度截断，防止大报文撑爆 JSONB 行。
"""

import logging
from typing import Any

from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)

_MAX_SNAPSHOT_LEN = 2000


def record_audit(
    action: str,
    *,
    operator: str | None = None,
    role: str | None = None,
    params: Any = None,
    result: str | None = None,
    client_ip: str | None = None,
    cost_ms: int | None = None,
) -> AuditLog | None:
    """写入一条审计日志；失败时记 error 日志并返回 None（不抛出）。"""
    try:
        return AuditLog.objects.create(
            action=action,
            operator=operator,
            role=role,
            params_snapshot=_truncate(params),
            result=result,
            client_ip=client_ip,
            cost_ms=cost_ms,
        )
    except Exception:
        logger.exception("audit_log 写入失败 action=%s operator=%s", action, operator)
        return None


def _truncate(value: Any) -> Any:
    text = repr(value)
    if len(text) > _MAX_SNAPSHOT_LEN:
        return text[:_MAX_SNAPSHOT_LEN]
    return value
