"""闲置资源清单读路径（api.md 接口16；工程约定 §2：selectors 只做读）。

判定口径不在本层：SQL 下推的是 `idle_rules.idle_branches()` 表达的**精确谓词**（未释放 ＋
选中支的 OR，spec §9 D14-a/g），纯列筛选由 `_column_filters()` 叠加；`judge` 仍逐行跑，
只负责出参文案与「SQL 命中 ⇒ judge 必命中」的对拍（等价性由 tests/test_idle_sql_equiv.py
钉住）。排序当前仍在 Python 侧 `_sort_rows`（api.md 接口16：排序服务端全量执行），分页交
视图层 `ResultPaginator`。本层不感知角色。

取数形状是 `_PROJECTION` 这 15 列的投影（spec §8.1 方案 3 + 方案 5），既不取整行也不 JOIN
账号表：5 万行实测把这两步的代价量过（1911ms 整行 → 624ms 投影；其中去 JOIN 值 662ms），
代价全部落在**客户端逐行取回**上，DB 侧执行只 22.8ms。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import reduce
from operator import or_
from typing import Any, Protocol

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.assets.idle_rules import (
    IDLE_SINCE,
    IDLE_SINCE_ALIAS,
    IDLE_TYPES,
    IdleConfig,
    IdleSource,
    IdleVerdict,
    idle_branches,
    judge,
)
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


# 投影列（规格 §8.1 方案 3）：`judge` 的输入契约 + 序列化层出参 + 归属解析 + 排序次级键的并集。
# 与 `IdleCandidate` 的字段**同名同序**——行对象按位置构造，这条绑定由
# tests/test_idle_selectors.py::test_projection_columns_are_the_row_fields_in_order 钉住。
_PROJECTION: tuple[str, ...] = (
    "id",
    "released_at",
    "status_changed_at",
    "first_seen_at",
    "create_time",
    "expire_time",
    "charge_type",
    "status",
    "resource_type",
    "instance_id",
    "instance_name",
    "region",
    "project_tag",
    "registrar",
    "cloud_account_id",
)


@dataclass(frozen=True, slots=True)
class IdleCandidate:
    """一行候选：投影列的值，**不是** `CloudAsset` 对象。

    取代整行取回的动机是实测，不是审美：5 万行同一候选集下，不建模型对象的投影 **624ms** vs
    整行模型对象 **1911ms**；5 进程并发下 P95 **3016 → 1772**（规格 §8.1，进程内脚本档位；
    部署形态复测 2808ms 未达标，见规格 §8.3）。
    `slots` 让 4 万个实例少一份 `__dict__`。`pk` 是 `CloudAsset` 侧的同名替身，供排序次级键
    与既有用例使用（`id` 才是列名，见 `_PROJECTION`）。
    """

    id: int
    released_at: datetime | None
    status_changed_at: datetime | None
    first_seen_at: datetime | None
    create_time: datetime | None
    expire_time: datetime | None
    charge_type: str | None
    status: str
    resource_type: str
    instance_id: str
    instance_name: str | None
    region: str | None
    project_tag: str | None
    registrar: str | None
    cloud_account_id: int | None

    @property
    def pk(self) -> int:
        return self.id


class IdleListSource(IdleSource, Protocol):
    """`IdleRow.asset` 的形状：判据所需（`IdleSource`）+ 出参、归属与排序次级键所需。

    写成协议而非具体类，是因为两侧都要能满足：读路径给 `IdleCandidate`，测试与任何手工构造
    的 `IdleRow` 给 `CloudAsset`（含未保存实例）。序列化层只按属性取值，两形同构。
    """

    @property
    def pk(self) -> int: ...

    @property
    def instance_id(self) -> str: ...

    @property
    def instance_name(self) -> str | None: ...

    @property
    def region(self) -> str | None: ...

    @property
    def project_tag(self) -> str | None: ...

    @property
    def registrar(self) -> str | None: ...

    @property
    def cloud_account_id(self) -> int | None: ...


@dataclass(frozen=True)
class IdleRow:
    """一行清单 = 资产（投影行或模型实例）+ 判定结论 + 已解析的归属账号名。"""

    asset: IdleListSource
    verdict: IdleVerdict
    account_name: str | None


def _account_names(assets: Sequence[IdleListSource]) -> dict[int, str]:
    """候选行引用到的账号名，一次读成 `{pk: account_name}`（规格 §8.1 方案 5）。

    读在候选快照**之后**：`on_delete=RESTRICT` 下被引用的账号删不掉，故这次读取必然覆盖
    快照里出现过的每个 `cloud_account_id`；反过来先读字典再扫资产才会漏掉其间新建的账号。
    """
    ids = {asset.cloud_account_id for asset in assets if asset.cloud_account_id is not None}
    if not ids:
        return {}
    return dict(CloudAccount.objects.filter(pk__in=ids).values_list("id", "account_name"))


def _account_name(asset: IdleListSource, names: dict[int, str]) -> str | None:
    """归属账号：域名取注册商，其余取云账号名（PRD 3.14-2）。"""
    if asset.resource_type == _DOMAIN:
        return asset.registrar
    if asset.cloud_account_id is None:
        return None
    # 缺键意味着上面那条 RESTRICT 前提被破坏（账号被硬删），宁可 500 也不要静默显示成「无归属」。
    return names[asset.cloud_account_id]


def _column_filters(qs: QuerySet[CloudAsset], filters: IdleQueryFilters) -> QuerySet[CloudAsset]:
    """纯列筛选（与判据无关，留在 SQL）：类型／账号／地域／项目／关键字。"""
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


def idle_predicate_sql(
    filters: IdleQueryFilters, config: IdleConfig, now: datetime
) -> QuerySet[CloudAsset]:
    """带精确判定谓词的候选集（spec §9 D14-a）：未释放 ＋ 选中支的 OR。

    **不含列筛选**——列筛选由 `_column_filters()` 在调用处叠加（分开是为了让
    `test_production_predicate_equals_branch_or_set` 能拿它和纯判据集合直接对拍）。
    没有 `status IN (...)` 预筛了：精确谓词本身蕴含那四个状态（D14-g）。

    Args:
        filters: 查询条件；只有 `idle_types` 参与谓词（取值已由序列化层校验为 `IDLE_TYPES`
            子集，故 `branches[t]` 不会 KeyError），为空表示四支全取。
        config: 阈值配置，与同请求的 `judge` 用**同一个**实例。
        now: 判定时钟，与同请求的 `judge` 用**同一个**时刻。

    Returns:
        带 `idle_since` 注解（支 ② 的谓词挂在它上面，缺注解 Django 会 FieldError）且已
        下推判定谓词的 `CloudAsset` QuerySet，未投影、未排序、未分页。
    """
    branches = idle_branches(config, now)
    types = filters.idle_types or list(IDLE_TYPES)
    predicate = reduce(or_, (branches[t] for t in types))
    return (
        CloudAsset.objects.filter(released_at__isnull=True)
        .annotate(**{IDLE_SINCE_ALIAS: IDLE_SINCE})
        .filter(predicate)
    )


@dataclass(frozen=True)
class IdleRead:
    """一次请求的读快照：阈值、时钟，与已下推谓词的投影 QuerySet（spec §9 D14）。

    `config` 与 `now` 在这里**只取一次**并贯穿到出参——判据 ② 的阈值若在这两步之间各读一
    次，SQL 筛的行与 `judge` 写的文案可能来自不同的 N。
    """

    config: IdleConfig
    now: datetime
    queryset: QuerySet[Any]

    def rows(self, chunk: Sequence[Sequence[Any]]) -> list[IdleRow]:
        """把一页（或整表）投影行组装成 `IdleRow`：`judge` 只在这里逐行跑。

        Args:
            chunk: `values_list(*_PROJECTION)` 的切片结果，列序由
                `test_projection_columns_are_the_row_fields_in_order` 钉住。

        Returns:
            `IdleRow` 列表，顺序即入参顺序——本函数不排序：当前由调用方的 `_sort_rows`
            负责，ORDER BY 下推后（Task 3）SQL 给出的顺序就是它。
        """
        assets = [IdleCandidate(*t) for t in chunk]
        names = _account_names(assets)
        rows: list[IdleRow] = []
        for asset in assets:
            verdict = judge(asset, self.config, self.now)
            if verdict is None:
                # SQL 谓词与 judge 等价（D14-e①）时此处不可达；真走到这里说明两份表达已分叉。
                # 宁可当场红，也不要静默少一行——`total` 是 SQL 算的，少行会让响应自相矛盾。
                raise AssertionError(f"SQL 命中但 judge 未命中：pk={asset.pk}（D14-e 等价性已破）")
            rows.append(
                IdleRow(asset=asset, verdict=verdict, account_name=_account_name(asset, names))
            )
        return rows


def prepare_idle_read(filters: IdleQueryFilters) -> IdleRead:
    """取一次阈值／时钟，下推判定谓词与列筛选，返回读上下文（视图与整表消费方共用）。

    Args:
        filters: 接口16 查询条件（已由序列化层校验）。

    Returns:
        `IdleRead`：投影 QuerySet 已带精确判定谓词与列筛选，**尚未**排序、**尚未**分页。
    """
    config = IdleConfig(idle_stopped_days=int(get_platform_setting("idle_stopped_days")))
    now: datetime = timezone.now()
    qs = _column_filters(idle_predicate_sql(filters, config, now), filters).values_list(
        *_PROJECTION
    )
    return IdleRead(config=config, now=now, queryset=qs)


def list_idle_assets(filters: IdleQueryFilters) -> list[IdleRow]:
    """返回命中四判据的闲置清单，已按 `sort_field` / `sort_order` 排好、未分页。

    整份取数（不分页）——接口 18 导出与既有测试的消费口。接口 16 的视图目前仍走本函数，
    每请求取回整表；谓词已下推，行数下推（ORDER BY ＋ LIMIT/OFFSET）归后续 Task，届时视图
    改用 `prepare_idle_read()` ＋ `ResultPaginator` ＋ `IdleRead.rows()`。

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
    read = prepare_idle_read(filters)
    rows = read.rows(list(read.queryset))
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
