"""闲置判定四判据（PRD 3.14-1 / Q17；spec §2 接缝 A）。

**判定口径的唯一实现**：查询接口与后续导出都只调 `judge`，禁止在 selector / serializer /
view 里复制判据条件（spec US-3）。`judge` 仍是纯函数（不碰 DB、时钟由调用方注入），F063 的
四类命中与阈值翻转全部打在这一层；`idle_branches()` 只**构造** ORM 查询表达式、不执行查询，
因此口径的两份表达仍留在同一个文件里，避免跨文件漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from django.db.models import Q
from django.db.models.functions import Coalesce
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


class IdleSource(Protocol):
    """`judge` 的输入契约：判据真正读到的那几列，命名与 `cloud_asset` 列同名。

    判据不再声明成 `CloudAsset`——读路径按投影取数（规格 §8.1 方案 3），5 万行实测里不建
    模型对象的投影取回 **624ms** vs 整行模型对象 **1911ms**，而判定口径仍只有 `judge` 一处
    实现：**换的是数据形状，不是口径**。成员一律写成只读 `@property`，协议因此按协变匹配，
    `CloudAsset`（`create_time` 由 `auto_now_add` 恒非空）与投影行（同列可为 NULL）都满足。
    """

    @property
    def released_at(self) -> datetime | None: ...

    @property
    def charge_type(self) -> str | None: ...

    @property
    def status(self) -> str: ...

    @property
    def resource_type(self) -> str: ...

    @property
    def status_changed_at(self) -> datetime | None: ...

    @property
    def first_seen_at(self) -> datetime | None: ...

    @property
    def create_time(self) -> datetime | None: ...

    @property
    def expire_time(self) -> datetime | None: ...


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


def stopped_since(asset: IdleSource) -> datetime | None:
    """停机起点三级回退（spec §8-D11）：`status_changed_at` → `first_seen_at` → `create_time`。

    `align_assets` 与 `upsert_domain` 都写前两个；Admin 单条维护写不到它们——
    `CloudAssetAdmin` 把两列列为只读，新建行两列皆空，其它未经这两条路径落库的
    行同样可能为空。`create_time` 由 `auto_now_add` 恒有值，语义同为「进入平台的
    时间」，故这一级回退不可省。
    代价：对「先入库、后停机」的行会低估停机时长（与 D8 的接受高估方向相反，已在 spec 登记）。

    Args:
        asset: 待取停机起点的资产（可以是未保存实例，口径同 `judge`）。

    Returns:
        三级回退中第一个非空的时间戳；三列皆空时为 None（判据 ② 此时不给结论）。
    """
    return asset.status_changed_at or asset.first_seen_at or asset.create_time


IDLE_SINCE_ALIAS = "idle_since"
# 停机起点的 SQL 表达 = `stopped_since()` 的三级回退（D14-b）。别名由读路径 annotate 出来，
# 判据 ② 的阈值比较必须挂在这个别名上——`Q(Coalesce(...), "lte", x)` 这种表达式位置参数
# 在 Django 5.2 会被拒（Cannot filter against a non-conditional expression）。
# 三级之间的顺序**有实义**：`align_assets` 与 `upsert_domain` 把第 1、2 级同时写进同一行，
# 取哪一级直接决定判据 ② 的日期来源。前两级互换必须让 `tests/test_idle_sql_equiv.py` 红——
# 钉这一格的是该文件里的单行用例 `test_idle_since_takes_level1_before_level2`（rowspace 每
# 行只填一档，抓不到它）。
IDLE_SINCE = Coalesce("status_changed_at", "first_seen_at", "create_time")


def idle_branches(config: IdleConfig, now: datetime) -> dict[str, Q]:
    """四判据的 SQL 谓词表达：`{idle_type: Q}`，与 `judge` 逐支等价（spec §9 D14-a）。

    每支对应 `judge` 里同序号的那条 `if`：分支间**互斥**（①② 要 `status=stopped` 并由
    `charge_type` 分家、③ 要 `unbound`、④ 要 `expired|expiring`，而 `status` 是单值列），
    所以短路顺序不影响命中集合，`idleType` 多选取子集 OR 与「先取回再按结论筛」同解。

    本函数不是第二套口径：语义以 `judge` 为准，等价性由
    `tests/test_idle_sql_equiv.py` 在全笛卡尔积上钉死（D14-e①）。改这里必须同轮改 `judge`
    并让那条测试先红后绿。

    Args:
        config: 阈值配置（只有 ② 用到 `idle_stopped_days`）。
        now: 与 `judge` **同一个**注入时刻；读路径每请求取一次、贯穿到出参。

    Returns:
        四支谓词。调用方必须自己带上 `released_at__isnull=True`（那是 `judge` 的第一条早退，
        不属于任何一支）。
    """
    stopped = CloudAsset.Status.STOPPED
    return {
        # ① 包年包月已停机（不需要时长依据）
        IDLE_PREPAID_STOPPED: Q(charge_type=_PREPAID, status=stopped),
        # ② 按量停机 ≥ N 天：floor 语义与整数 N ⇒ `>= N*86400s` 等价于 `<= now - N 天`
        IDLE_POSTPAID_STOPPED: Q(
            charge_type=_POSTPAID,
            status=stopped,
            **{f"{IDLE_SINCE_ALIAS}__lte": now - timedelta(days=config.idle_stopped_days)},
        ),
        # ③ EIP 未绑定
        IDLE_EIP_UNBOUND: Q(resource_type=_EIP, status=CloudAsset.Status.UNBOUND),
        # ④ 域名过期/即将到期：两个子分支都命中，差别只在文案（D14-c ⇒ SQL 里不做日期差）
        IDLE_DOMAIN_EXPIRED: Q(
            resource_type=_DOMAIN,
            status__in=[CloudAsset.Status.EXPIRED, CloudAsset.Status.EXPIRING],
        ),
    }


def judge(asset: IdleSource, config: IdleConfig, now: datetime) -> IdleVerdict | None:
    """按 PRD 3.14-1 四判据推导闲置结论，全不命中返回 None。

    Args:
        asset: 待判资产（`IdleSource`：未保存的 `CloudAsset` 实例与读路径的投影行都满足，
            前者便于纯口径测试，后者是生产形状）。
        config: 阈值配置（`idle_stopped_days`）。
        now: 调用方注入的当前时刻（aware datetime）。

    Returns:
        命中判据的结论；已软删资产与全不命中均为 None。

    SQL 下推表达见 `idle_branches`，等价性由 tests/test_idle_sql_equiv.py 钉住。
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
