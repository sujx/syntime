"""审计日志保留期清理（engineering-conventions §7 / PRD 4.4-5：audit_log 保留 12 个月）。

保留月数取自 ``platform_setting.audit_retention_months``（默认 12，见 common/readers），
由分区维护任务每月调用：删除 ``create_time`` 早于 cutoff 的行，返回删除条数。
边界为**严格早于**（``create_time < cutoff``），恰好等于 cutoff 的行保留。
"""

from __future__ import annotations

import logging
from datetime import datetime

from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)


def purge_audit_logs(before: datetime) -> int:
    """删除 ``create_time`` 严格早于 ``before`` 的审计日志，返回删除条数。"""
    deleted, _ = AuditLog.objects.filter(create_time__lt=before).delete()
    if deleted:
        logger.info("清理审计日志 %d 条（早于 %s）", deleted, before)
    return deleted
