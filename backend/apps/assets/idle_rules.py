"""闲置判定四判据（PRD 3.14-1 / Q17；spec §2 接缝 A）。

**判定口径的唯一实现**：查询接口与后续导出都只调 `judge`，禁止在 selector / serializer /
view 里复制判据条件（spec US-3）。纯函数、不碰 DB、时钟由调用方注入，F063 的四类命中与
阈值翻转全部打在这一层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from apps.assets.models import CloudAsset

# idle_type 取值（api.md 接口16 的 idleType 枚举，单一来源）
IDLE_PREPAID_STOPPED = "prepaid_stopped"
IDLE_POSTPAID_STOPPED = "postpaid_stopped"
IDLE_EIP_UNBOUND = "eip_unbound"
IDLE_DOMAIN_EXPIRED = "domain_expired"

# 元组顺序 **就是** 判定短路顺序（spec US-3「多命中取第一类」）。当前四判据因 `status`
# 单值而结构上不可能多命中，顺序仍按编号排列：它同时是 api.md 接口16 `idleType` 的枚举顺序。
IDLE_TYPES: tuple[str, ...] = (
    IDLE_PREPAID_STOPPED,
    IDLE_POSTPAID_STOPPED,
    IDLE_EIP_UNBOUND,
    IDLE_DOMAIN_EXPIRED,
)

# PRD 3.14-4 误报提示：接口出参 notice 的唯一来源，前端原样展示
IDLE_NOTICE = "闲置为状态推导的疑似结果，有意停机的资源请忽略"

# 四判据的**必要条件下推**集合（spec §8-D12）：命中任一判据必然落在此状态集内，
# 用它做 SQL 预筛只减少 Python 侧行数、不改变结果。**这不是判定口径**，改它必须
# 同步通过 tests/test_idle_selectors.py 的候选等价性测试。
IDLE_CANDIDATE_STATUSES: tuple[str, ...] = (
    CloudAsset.Status.STOPPED,
    CloudAsset.Status.UNBOUND,
    CloudAsset.Status.EXPIRED,
    CloudAsset.Status.EXPIRING,
)

_PREPAID = "prepaid"
_POSTPAID = "postpaid"
_EIP = "eip"
_DOMAIN = "domain"


@dataclass(frozen=True)
class IdleConfig:
    """判定输入配置。每请求从 `platform_setting` 读，改值无需重启（spec US-4）。"""

    idle_stopped_days: int


@dataclass(frozen=True)
class IdleVerdict:
    """一行资产的结论：命中哪一类 + 人读判定依据 + 关键值（停机天数、剩余天数）。"""

    idle_type: str
    reason: str
    key_metric: dict[str, int] = field(default_factory=dict)


def stopped_since(asset: CloudAsset) -> datetime | None:
    """停机起点三级回退（spec §8-D11）：`status_changed_at` → `first_seen_at` → `create_time`。

    `align_assets` 与 `upsert_domain` 都写前两个，但 `seed_demo` 与 Admin 手工录入的行实测
    两列皆空；`create_time` 由 `auto_now_add` 恒有值，语义同为「进入平台的时间」。
    代价：对「先入库、后停机」的行会低估停机时长（与 D8 的接受高估方向相反，已在 spec 登记）。
    """
    return asset.status_changed_at or asset.first_seen_at or asset.create_time


def judge(asset: CloudAsset, config: IdleConfig, now: datetime) -> IdleVerdict | None:
    """按 PRD 3.14-1 四判据推导闲置结论，全不命中返回 None。

    Args:
        asset: 待判资产（可以是未保存实例，便于纯口径测试）。
        config: 阈值配置（`idle_stopped_days`）。
        now: 调用方注入的当前时刻（aware datetime）。

    Returns:
        命中判据的结论；已软删资产与全不命中均为 None。
    """
    if asset.released_at is not None:
        return None

    # ① 包年包月已停机：停机了钱照扣，最典型浪费（不需要时长依据）
    if asset.charge_type == _PREPAID and asset.status == CloudAsset.Status.STOPPED:
        return IdleVerdict(IDLE_PREPAID_STOPPED, "包年包月资源已停机")

    # ② 按量付费长期停机：持续 ≥ idle_stopped_days 天
    if asset.charge_type == _POSTPAID and asset.status == CloudAsset.Status.STOPPED:
        since = stopped_since(asset)
        if since is not None:
            days = (now - since).days
            if days >= config.idle_stopped_days:
                return IdleVerdict(
                    IDLE_POSTPAID_STOPPED,
                    f"按量付费已停机 {days} 天（阈值 {config.idle_stopped_days} 天）",
                    {"stoppedDays": days, "thresholdDays": config.idle_stopped_days},
                )

    # ③ EIP 未绑定
    if asset.resource_type == _EIP and asset.status == CloudAsset.Status.UNBOUND:
        return IdleVerdict(IDLE_EIP_UNBOUND, "EIP 处于未绑定状态")

    # ④ 域名已过期 / 即将到期：读存量 status（口径同 PRD 3.13-4），不在查询时重算
    if asset.resource_type == _DOMAIN and asset.status in {
        CloudAsset.Status.EXPIRED,
        CloudAsset.Status.EXPIRING,
    }:
        if asset.expire_time is None:
            return IdleVerdict(IDLE_DOMAIN_EXPIRED, "域名已过期或即将到期（台账无到期时间）")
        days_until = (timezone.localdate(asset.expire_time) - timezone.localdate(now)).days
        if days_until < 0:
            return IdleVerdict(
                IDLE_DOMAIN_EXPIRED,
                f"域名已过期 {abs(days_until)} 天",
                {"daysUntilExpiry": days_until},
            )
        return IdleVerdict(
            IDLE_DOMAIN_EXPIRED,
            f"域名 {days_until} 天后到期",
            {"daysUntilExpiry": days_until},
        )

    return None
