"""闲置资源清单读路径（api.md 接口16；工程约定 §2：selectors 只做读）。

判定口径不在本层：SQL 只下推**必要条件**（未释放 + 状态 ∈ `IDLE_CANDIDATE_STATUSES`，
spec §8-D12）与纯列筛选，逐行判定一律交给 `idle_rules.judge`；`idleType` 过滤与排序在
判定后于 Python 侧完成（api.md 接口16：排序服务端全量执行），分页交视图层 `ResultPaginator`。
本层不感知角色。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.assets.idle_rules import IDLE_CANDIDATE_STATUSES, IdleConfig, IdleVerdict, judge
from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount
from common.readers import get_platform_setting

# 可排序的模型字段（API 的 camelCase 已在序列化层映射过来）
_SORTABLE = frozenset(
    {"instance_id", "resource_type", "status", "region", "project_tag", "expire_time"}
)
DEFAULT_SORT_FIELD = "expire_time"
_DOMAIN = "domain"


@dataclass(frozen=True)
class IdleQueryFilters:
    """接口16 查询条件（已由序列化层校验）。"""

    idle_types: list[str] = field(default_factory=list)
    resource_type: str | None = None
    cloud_account_id: int | None = None
    region: str | None = None
    project_tag: str | None = None
    keyword: str | None = None
    sort_field: str = DEFAULT_SORT_FIELD
    sort_order: str = "asc"


@dataclass(frozen=True)
class IdleRow:
    """一行清单 = 资产 + 判定结论 + 已解析的归属账号名。"""

    asset: CloudAsset
    verdict: IdleVerdict
    account_name: str | None


def _account_name(asset: CloudAsset) -> str | None:
    """归属账号：域名取注册商，其余取云账号名（PRD 3.14-2）。"""
    if asset.resource_type == _DOMAIN:
        return asset.registrar
    if asset.cloud_account_id is None:
        return None
    # 非空 id 在 `on_delete=RESTRICT` 下必能解析到已 join 的账号行，故只做静态收窄、不加运行时兜底。
    return cast(CloudAccount, asset.cloud_account).account_name


def _candidate_queryset(filters: IdleQueryFilters) -> QuerySet[CloudAsset]:
    """候选集：必要条件预筛（不改变结果，见 test_candidate_prefilter_is_lossless）+ 纯列筛选。"""
    qs = CloudAsset.objects.filter(
        released_at__isnull=True,
        status__in=list(IDLE_CANDIDATE_STATUSES),
    ).select_related("cloud_account")
    if filters.resource_type:
        qs = qs.filter(resource_type=filters.resource_type)
    if filters.cloud_account_id is not None:
        qs = qs.filter(cloud_account_id=filters.cloud_account_id)
    if filters.region:
        qs = qs.filter(region=filters.region)
    if filters.project_tag:
        qs = qs.filter(project_tag=filters.project_tag)
    if filters.keyword:
        kw = filters.keyword
        qs = qs.filter(
            Q(instance_id__icontains=kw)
            | Q(instance_name__icontains=kw)
            | Q(registrar__icontains=kw)
        )
    return qs


def list_idle_assets(filters: IdleQueryFilters) -> list[IdleRow]:
    """返回命中四判据的闲置清单，已按 `sort_field` / `sort_order` 排好、未分页。

    `idle_stopped_days` 每请求经 `get_platform_setting` 两级回退读取（spec US-4）。

    两条 Task 3/4/6 要照单继承的既定口径：

    - **归属优先级**：`resource_type == "domain"` 行的 `account_name` 取**注册商**
      （PRD 3.14-2），这就是产品规则本身，故域名行即便挂了 `cloud_account` 也显示注册商。
    - **次级键方向**：非空桶的 `pk` 跟随 `sort_order`（`desc` 即 `pk DESC`），空值桶恒
      `pk ASC`；对**已保存行**（`pk` 非空）`pk` 唯一，两个方向都是**严格全序**、跨调用稳定。
      未保存行只可能来自手工构造的 `IdleRow`（本函数的读路径拿不到），其 `pk` 为 None ⇒
      次级键恒等于 0，主键也相同时退回输入顺序，全序不成立。

    Args:
        filters: 接口16 查询条件（已由序列化层校验）。`sort_field` 不在白名单时回退
            `expire_time`；`idle_types` 为空表示不按闲置类型筛。

    Returns:
        命中判据的 `IdleRow` 列表（资产 + `judge` 结论 + 已解析的归属账号名），
        已全量排序、未分页（分页交视图层 `ResultPaginator`）；无命中时为空列表。
    """
    config = IdleConfig(idle_stopped_days=int(get_platform_setting("idle_stopped_days")))
    now: datetime = timezone.now()
    rows: list[IdleRow] = []
    for asset in _candidate_queryset(filters):
        verdict = judge(asset, config, now)
        if verdict is None:
            continue
        if filters.idle_types and verdict.idle_type not in filters.idle_types:
            continue
        rows.append(IdleRow(asset=asset, verdict=verdict, account_name=_account_name(asset)))
    return _sort_rows(rows, filters)


def _sort_rows(rows: list[IdleRow], filters: IdleQueryFilters) -> list[IdleRow]:
    """服务端全量排序：空值恒排最后（不随升降序翻转），`pk` 作稳定次级键免翻页跳动。

    排序必须是**全序**：候选集 SQL 不带 ORDER BY，空值桶若沿用扫描顺序，同一批行在翻页时
    会随物理顺序漂动，故空值桶也显式按 `pk` 升序收口。这一收口的前提是**已保存行**（`pk`
    非空）：次级键写作 `row.asset.pk or 0`，未保存行的 `pk` 为 None ⇒ 全部落到 0，主键也相同
    时只能退回输入顺序。生产读路径（`list_idle_assets`）只会喂已保存行，未保存行仅出现在
    手工构造 `IdleRow` 的测试里。
    """
    name = filters.sort_field if filters.sort_field in _SORTABLE else DEFAULT_SORT_FIELD
    reverse = filters.sort_order == "desc"
    present = [row for row in rows if getattr(row.asset, name) is not None]
    missing = [row for row in rows if getattr(row.asset, name) is None]
    present.sort(key=lambda row: (getattr(row.asset, name), row.asset.pk or 0), reverse=reverse)
    missing.sort(key=lambda row: row.asset.pk or 0)
    return present + missing
