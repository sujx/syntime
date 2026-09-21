"""平台自算检测任务（tasks.md 任务 8 / PRD 3.12-8，platform.md 9.1 Celery + beat）。

单入口 ``self_calc_detect``：每小时一次，跑厂商消息不覆盖的两类自算检测——
域名到期（T-30/T-7/T-1 + 过期）与预算超支（按 2.2.2 口径首次破 100%）。
两类均以业务键 dedup 去重，重复扫描幂等（V1.10 起停机不再自算兜底，Q9=B）。

互斥锁 / 退避重试 / 审计钩子统一走 ``SynTimeTask`` 基类（§5.1），此处仅设
``audit_action="detect"``（AuditLog.Action 枚举内）。检测口径全在 ``services``，
任务层不重复实现，仅负责调度窗口与计数汇总。
"""

from __future__ import annotations

from datetime import date

from apps.events.services import detect_budget_overrun, detect_domain_expiry
from common.tasks import SynTimeTask
from config.celery import app


class _DetectTask(SynTimeTask):
    abstract = True
    audit_action = "detect"


@app.task(base=_DetectTask, bind=True, name="events.self_calc_detect")
def self_calc_detect(
    self,
    today_iso: str | None = None,
    bill_month: str | None = None,
    operator: str | None = None,
) -> dict[str, int]:
    """扫描并以幂等方式落自算事件，返回 ``{"domain": n, "budget": m}`` 新建计数。

    ``today_iso`` / ``bill_month`` 缺省时由各检测函数取本地当日 / 当账期月；
    显式传值供手动触发与测试注入确定时间。
    """
    today = date.fromisoformat(today_iso) if today_iso else None
    domain = detect_domain_expiry(today=today)
    budget = detect_budget_overrun(bill_month=bill_month, today=today)
    return {"domain": domain, "budget": budget}
