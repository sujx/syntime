"""成本预聚合任务（tasks.md 任务2，platform.md 9.1 Celery + beat）。

两个入口：
- ``aggregate_cost_daily``：按指定 ``[start, end]`` 窗口聚合，供账单同步完成后链式触发
  与成本管理员手动触发（手动触发接口若任务在跑由互斥锁返回 40900）；
- ``reaggregate_previous_month``：每月 3 日 beat 触发，对上一账期自然月全量重算
  （正式账单落地后修正预估，tasks.md 任务2-④）。

互斥锁 / 退避重试 / 审计钩子统一走 ``SynTimeTask`` 基类（§5.1），此处仅设
``audit_action="aggregate"``（AuditLog.Action 枚举内）。聚合落库口径全在
``services.aggregate_daily``，任务层不重复实现。
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.cost.services import aggregate_daily
from common.tasks import SynTimeTask
from config.celery import app


def previous_month_range(today: date) -> tuple[date, date]:
    """上一账期自然月的 ``[首日, 末日]``（自动处理跨年与闰月）。"""
    first_this_month = today.replace(day=1)
    last_prev = first_this_month - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


class _AggregateTask(SynTimeTask):
    abstract = True
    audit_action = "aggregate"


@app.task(base=_AggregateTask, bind=True, name="cost.aggregate_daily")
def aggregate_cost_daily(self, start: str, end: str, operator: str | None = None) -> dict:
    """聚合 ``[start, end]``（ISO 日期串）账单为日成本，覆盖写。"""
    deleted, inserted = aggregate_daily(date.fromisoformat(start), date.fromisoformat(end))
    return {"deleted": deleted, "inserted": inserted, "start": start, "end": end}


@app.task(base=_AggregateTask, bind=True, name="cost.reaggregate_previous_month")
def reaggregate_previous_month(
    self, today_iso: str | None = None, operator: str | None = None
) -> dict:
    """对上一账期自然月全量重算；``today_iso`` 可注入以便测试，默认取系统当日。"""
    today = date.fromisoformat(today_iso) if today_iso else date.today()
    start, end = previous_month_range(today)
    deleted, inserted = aggregate_daily(start, end)
    return {
        "deleted": deleted,
        "inserted": inserted,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
