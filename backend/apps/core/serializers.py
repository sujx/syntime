"""仪表盘聚合接口序列化层（api.md 接口9）。

职责：把 ``apps.core.selectors`` 的 cards/syncStatus 数据类翻译为 camelCase JSON，
金额两位小数字符串、比率/环比口径上的 ``None`` 翻译为 ``--``（复用 cost 序列化约定，
禁止用 0 冒充）；trend 块直接复用接口8 的 ``TrendResultSerializer``（结构一致，
仅分组维度由 resource_type 决定，projectTag 承载资源类型码）。
"""

from __future__ import annotations

from apps.core.selectors import DashboardCards, SyncStatus
from apps.cost.serializers import _money_or_dash


def cards_payload(cards: DashboardCards) -> dict[str, object]:
    """接口9 ``cards`` 块（PRD 3.10-1 五张 KPI 卡片）。"""
    return {
        "cloudAccountTotal": cards.cloud_account_total,
        "enabled": cards.enabled,
        "disabled": cards.disabled,
        "assetTotal": cards.asset_total,
        "running": cards.running,
        "stopped": cards.stopped,
        "monthAmount": _money_or_dash(cards.month_amount),
        "monthRate": _money_or_dash(cards.month_rate),
        "isEstimate": cards.is_estimate,
        "unallocatedAmount": _money_or_dash(cards.unallocated_amount),
        "unallocatedRatio": _money_or_dash(cards.unallocated_ratio),
        "eventPending": cards.event_pending,
        "eventHigh": cards.event_high,
        "eventWarning": cards.event_warning,
    }


def sync_status_payload(sync: SyncStatus) -> dict[str, object]:
    """接口9 ``syncStatus`` 块（复用接口6：各账号最近同步 + 最近聚合完成时间）。"""
    return {
        "accounts": [
            {
                "accountName": a.account_name,
                "vendor": a.vendor,
                "lastSyncTime": a.last_sync_time.isoformat() if a.last_sync_time else None,
                "status": a.status,
            }
            for a in sync.accounts
        ],
        "lastAggregateTime": (
            sync.last_aggregate_time.isoformat() if sync.last_aggregate_time else None
        ),
    }
