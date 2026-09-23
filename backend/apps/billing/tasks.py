"""分区维护任务（tasks.md 任务 6 / PRD 4.4-5，platform.md 9.1 Celery + beat）。

单入口 ``partition_maintenance``：每月 1 日 01:00 一次，编排三件事——
预建当月 + 未来 2 个月的账单分区、DETACH 超过 24 个月在线保留期的旧账单分区、
清理超过 ``audit_retention_months``（默认 12）保留期的审计日志。
DDL 与清理口径分别在 ``billing.partitions`` / ``audit.services``，任务层只做调度与汇总。

互斥锁 / 退避重试 / 审计钩子统一走 ``SynTimeTask`` 基类（§5.1），此处仅设
``audit_action="maintain"``（AuditLog.Action 枚举内）。
"""

from __future__ import annotations

from datetime import date, datetime, time

from django.utils import timezone

from apps.audit.services import purge_audit_logs
from apps.billing.partitions import (
    detach_partitions_before,
    ensure_future_partitions,
    retention_cutoff,
)
from common.readers import get_platform_setting
from common.tasks import SynTimeTask
from config.celery import app


class _MaintenanceTask(SynTimeTask):
    abstract = True
    audit_action = "maintain"


@app.task(base=_MaintenanceTask, bind=True, name="billing.partition_maintenance")
def partition_maintenance(self, today_iso: str | None = None, operator: str | None = None) -> dict:
    """预建 + 归档账单分区并清理过期审计日志。

    ``today_iso`` 可注入以便测试，默认取本地当日。返回
    ``{"ensured": [...新建分区名], "detached": [...脱离分区名], "audit_purged": n}``。
    """
    today = date.fromisoformat(today_iso) if today_iso else timezone.localdate()

    ensured = ensure_future_partitions(today)
    detached = detach_partitions_before(retention_cutoff(today))

    audit_months = get_platform_setting("audit_retention_months")
    audit_cutoff_date = retention_cutoff(today, audit_months)
    audit_cutoff = timezone.make_aware(datetime.combine(audit_cutoff_date, time.min))
    audit_purged = purge_audit_logs(audit_cutoff)

    return {"ensured": ensured, "detached": detached, "audit_purged": audit_purged}
