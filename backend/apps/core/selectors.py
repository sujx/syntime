"""仪表盘跨模块聚合读路径（api.md 接口9 cards + 接口6 syncStatus）。

仪表盘是首页跨模块总览，数据源横跨 billing/assets/cost/events/audit，故落在
无业务归属的 ``apps.core``。**全部复用既有口径，不新造统计定义**（PRD 3.10）：
环比走 ``cost.services.previous_period/mom_change_pct``（等长前移）、未分配 =
unassigned + conflict（PRD 2.1.1）、事件级别取 ``cloud_event.event_level``。

- 资产计数排除软删（``released_at`` 非空）——已释放实例不计入「现有资源」；
- 待处理事件 = 未读（PRD 3.12-1：未读事件数同步到仪表盘「待处理事件」卡片），
  高危/警告按 event_level 拆分；
- syncStatus 的各账号最近同步时间取 ``CloudAccount.last_sync_time``（「最近成功
  同步」字段，同步任务成功时回写），最近一次同步**状态**取各账号最近一条
  ``sync_log``（含同步中/失败），最近聚合完成时间取最近一条 ``aggregate`` 成功审计。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Sum

from apps.assets.models import CloudAsset
from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, SyncLog
from apps.cost.models import ProjectCostDaily
from apps.cost.services import (
    TAG_CONFLICT,
    TAG_UNASSIGNED,
    covered_bill_months,
    mom_change_pct,
    previous_period,
)
from apps.events.models import CloudEvent

_PENDING_STATUSES = (CloudEvent.Status.UNREAD,)
_UNALLOCATED_STATUSES = (TAG_UNASSIGNED, TAG_CONFLICT)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class DashboardCards:
    """接口9 ``cards`` 块（金额为 Decimal，占比/环比 None 即口径上的「--」）。"""

    cloud_account_total: int
    enabled: int
    disabled: int
    asset_total: int
    running: int
    stopped: int
    month_amount: Decimal
    month_rate: Decimal | None
    is_estimate: bool
    unallocated_amount: Decimal
    unallocated_ratio: Decimal | None
    event_pending: int
    event_high: int
    event_warning: int


@dataclass(frozen=True)
class SyncStatusAccount:
    account_name: str
    vendor: str
    last_sync_time: datetime | None
    status: str | None


@dataclass(frozen=True)
class SyncStatus:
    accounts: list[SyncStatusAccount]
    last_aggregate_time: datetime | None


def _sum_amount(start: date, end: date, *, tag_statuses: tuple[str, ...] | None = None) -> Decimal:
    qs = ProjectCostDaily.objects.filter(stat_date__gte=start, stat_date__lte=end)
    if tag_statuses is not None:
        qs = qs.filter(tag_status__in=tag_statuses)
    return qs.aggregate(total=Sum("amount"))["total"] or _ZERO


def dashboard_cards(today: date) -> DashboardCards:
    """聚合首页 5 张 KPI 卡片的数值（PRD 3.10-1）。``today`` 可注入以便测试。"""
    month_start = today.replace(day=1)
    prev_start, prev_end = previous_period(month_start, today)

    month_amount = _sum_amount(month_start, today)
    prev_amount = _sum_amount(prev_start, prev_end)
    unallocated_amount = _sum_amount(month_start, today, tag_statuses=_UNALLOCATED_STATUSES)
    this_month = f"{today.year:04d}-{today.month:02d}"
    is_estimate = this_month in covered_bill_months(month_start, today)

    unallocated_ratio = (
        unallocated_amount / month_amount * Decimal(100) if month_amount > 0 else None
    )

    active_assets = CloudAsset.objects.filter(released_at__isnull=True)
    pending_events = CloudEvent.objects.filter(status__in=_PENDING_STATUSES)

    return DashboardCards(
        cloud_account_total=CloudAccount.objects.count(),
        enabled=CloudAccount.objects.filter(status=CloudAccount.Status.ENABLED).count(),
        disabled=CloudAccount.objects.filter(status=CloudAccount.Status.DISABLED).count(),
        asset_total=active_assets.count(),
        running=active_assets.filter(status=CloudAsset.Status.RUNNING).count(),
        stopped=active_assets.filter(status=CloudAsset.Status.STOPPED).count(),
        month_amount=month_amount,
        month_rate=mom_change_pct(month_amount, prev_amount),
        is_estimate=is_estimate,
        unallocated_amount=unallocated_amount,
        unallocated_ratio=unallocated_ratio,
        event_pending=pending_events.count(),
        event_high=pending_events.filter(event_level=CloudEvent.EventLevel.CRITICAL).count(),
        event_warning=pending_events.filter(event_level=CloudEvent.EventLevel.WARNING).count(),
    )


def sync_status() -> SyncStatus:
    """各云账号最近一次同步状态 + 最近一次成本聚合完成时间（api.md 接口6）。"""
    accounts: list[SyncStatusAccount] = []
    for account in CloudAccount.objects.order_by("id"):
        latest = (
            SyncLog.objects.filter(cloud_account=account).order_by("-start_time", "-id").first()
        )
        accounts.append(
            SyncStatusAccount(
                account_name=account.account_name,
                vendor=account.vendor,
                last_sync_time=account.last_sync_time,
                status=latest.status if latest else None,
            )
        )
    last_aggregate_time = (
        AuditLog.objects.filter(action=AuditLog.Action.AGGREGATE, result="success")
        .order_by("-create_time")
        .values_list("create_time", flat=True)
        .first()
    )
    return SyncStatus(accounts=accounts, last_aggregate_time=last_aggregate_time)
