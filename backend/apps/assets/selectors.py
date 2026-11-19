"""闲置资源清单读路径（api.md 接口16；工程约定 §2：selectors 只做读）。

判定谓词、ORDER BY、分页**三样全在 SQL**（spec §9 D14-a/d/f/g，2026-11-19 落地）：谓词是
`idle_rules.idle_branches()` 表达的**精确判据**（未释放 ＋ 选中支的 OR，D14-a/g；「SQL 只下推
必要条件」那一版预筛已按 D14-g 删除），纯列筛选由 `_column_filters()` 叠加，ORDER BY 由
`order_by_key()` 给出（api.md 接口16「服务端全量排序」的全序语义由它承接），分页交视图层
`ResultPaginator` 对**已排序的投影 QuerySet** 切片 ⇒ 每请求只回一页、`total` 由 SQL `COUNT`
给出；整份取回的形状只剩 `list_idle_assets()` 那条整表档（筛与排同样已在 SQL 里，只是不分页）。

`judge` 仍逐行跑，但**只跑页内行**（走整表档时是整份命中行），职责是出参文案；它还兼任最后一
道防线——命中集由 SQL 筛出后，若某行 `judge` 判不中，`IdleRead.rows()` 当场
`AssertionError`，绝不静默少一行（`total` 是 SQL 算的，少行会让响应自相矛盾）。口径等价性由
两道保险钉住：仓内 `tests/test_idle_sql_equiv.py`（全笛卡尔穷举 ＋ 生产谓词接线半边），与
2026-11-19 取证轮在 5 万行库上的新旧双臂对拍（候选 40012、命中 37511，9 个排序面双向差集 0、
顺序逐位相同）。本层不感知角色。

取数形状是 `_PROJECTION` 这 **15 投影列**（spec §8.1 方案 3 + 方案 5），既不取整行也不 JOIN
账号表。注意 **15 是投影列宽、11 是 `IdleRowSerializer` 的出参字段数**，两个数不是一回事、
别混用：15 列里直接进 11 个出参字段的只有 7 列（`instance_id`/`instance_name`/`resource_type`/
`region`/`project_tag`/`status`/`expire_time`），余下 8 列各有用处——`registrar` 与
`cloud_account_id` 供归属解析（出参那个 `cloudAccountName`），`id` 是排序次级键，
`released_at`/`status_changed_at`/`first_seen_at`/`create_time`/`charge_type` 供 `judge`
与 SQL 谓词。
「1911ms 整行 → 624ms **11 键投影**、去 JOIN 值 662ms（1911→1249）、DB 侧执行只 22.8ms、
代价全落在**客户端逐行取回**上」是 2026-11-18 §8.1 在整表档上量出来的读数（§8.2 与 §8.3 的
同形状后续读数记在 `IdleCandidate` 的 docstring 里）；2026-11-19 分页下推后视图每请求只取回
一页，那段取回代价只剩 `list_idle_assets()` 这条整表档还在付（2026-11-19 下推取证轮的同轮
读数：函数级 `new-page` median **62ms** vs `old` **2050ms**，HTTP P95 **130ms**／排序＋深翻页
**176ms**，门槛口径 5 并发 P95 ≤ 2000ms）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import reduce
from operator import or_
from typing import Any, Protocol

from django.db.models import BigIntegerField, Case, F, Q, QuerySet, When
from django.db.models.functions import Collate
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

    取代整行取回的动机是实测，不是审美。下面几个数是**带日期的历史读数**，量的都是**整表取回**
    那一档：2026-11-18 规格 §8.1 方案 3——同候选集下不建模型对象的 11 键投影 **624ms** vs 整行
    模型对象 **1911ms**（§8.2 再在含全部出参列的这 15 列形状上给出 **661ms** vs 改动前
    **1837ms**），5 进程并发下 P95 **3016 → 1772**（规格 §8.1，进程内脚本档位）；2026-11-19
    规格 §8.3 把同一形状改打部署形态（gunicorn ＋ 真 HTTP）复测，5 并发 P95 **2808ms**
    （门槛口径：5 并发 P95 ≤ 2000ms）。

    新事实（2026-11-20 记录；形状由 2026-11-19 的 D14 下推改掉）：接口 16 的视图每请求只构造
    **一页**的行对象，**不再逐行取回那 4 万候选**，上面那几个整表档读数因此都不再是视图的
    代价（视图档读数见模块 docstring）。`slots` 省掉的那份 `__dict__`，如今只在整表档
    （`list_idle_assets`，一次几万个实例）上才划算——视图档一页至多 100 个实例。`pk` 是
    `CloudAsset` 侧的同名替身，供排序次级键与既有用例使用（`id` 才是列名，见 `_PROJECTION`）。
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


# 文本排序键（D14-f）：这些列在库里是 UTF-8 text，本机 collation 是 en_HK.UTF-8，
# 与 Python `str` 的码位序不同 ⇒ 一律包 `Collate(expr, "C")`，否则 LIMIT 取到另一批行。
_TEXT_SORT_KEYS = frozenset({"instance_id", "resource_type", "status", "region", "project_tag"})
# 非空/空两桶的次级键符号随方向变（D14-d）：desc 时非空桶要 pk DESC（写作 -pk ASC），
# asc 时非空桶要 pk ASC —— 无条件的 -pk 只在 desc 对，是 spec 点名的错法。


def order_by_key(filters: IdleQueryFilters) -> list[Any]:
    """把 2026-11-19 之前那份 Python 侧全量排序（已随分页下推删除）的三条语义翻成 ORDER BY。

    三条是：键值 NULLS LAST（空值桶恒最后，不随方向翻转）、非空桶次级键 `pk` 跟随方向、
    空值桶次级键恒 `pk` ASC——少了第三条就不是全序，`LIMIT` 翻页会重行或漏行。逐条的牙在
    `tests/test_idle_selectors.py::test_sql_order_is_total_and_pages_stitch_without_overlap`。

    Args:
        filters: 取 `sort_field`（白名单外回退 `expire_time`）与 `sort_order`。

    Returns:
        可直接喂 `QuerySet.order_by()` 的表达式列表，恒两项。
    """
    name = filters.sort_field if filters.sort_field in _SORTABLE else DEFAULT_SORT_FIELD
    desc = filters.sort_order == "desc"
    # `primary` 必须是 `Any`：`Collate`/`F` 的 `.desc()/.asc()` 返回 `OrderBy`，
    # 复用同一变量会被 mypy 判 `Incompatible types in assignment`（本机 django-stubs 实测）。
    primary: Any = Collate(F(name), "C") if name in _TEXT_SORT_KEYS else F(name)
    ordered = primary.desc(nulls_last=True) if desc else primary.asc(nulls_last=True)
    tie = Case(
        When(Q(**{f"{name}__isnull": True}), then=F("id")),
        default=-F("id") if desc else F("id"),
        output_field=BigIntegerField(),
    )
    return [ordered, tie.asc()]


@dataclass(frozen=True)
class IdleRead:
    """一次请求的读快照：阈值、时钟，与已下推谓词＋排序的投影 QuerySet（spec §9 D14）。

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
            `IdleRow` 列表，顺序即入参顺序——本函数不排序：ORDER BY 已下推（见
            `order_by_key()`），SQL 给出的顺序就是它。
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
    """取一次阈值／时钟，下推判定谓词、列筛选与排序，返回读上下文（视图与整表消费方共用）。

    Args:
        filters: 接口16 查询条件（已由序列化层校验）。

    Returns:
        `IdleRead`：投影 QuerySet 已带精确判定谓词、列筛选与 ORDER BY，**尚未**分页——
        分页交调用方（视图层 `ResultPaginator` 对 QuerySet 切片，`total` 走 SQL `COUNT`）。
    """
    config = IdleConfig(idle_stopped_days=int(get_platform_setting("idle_stopped_days")))
    now: datetime = timezone.now()
    qs = _column_filters(idle_predicate_sql(filters, config, now), filters)
    qs = qs.order_by(*order_by_key(filters)).values_list(*_PROJECTION)
    return IdleRead(config=config, now=now, queryset=qs)


def list_idle_assets(filters: IdleQueryFilters) -> list[IdleRow]:
    """返回命中四判据的闲置清单，已按 `sort_field` / `sort_order` 排好、未分页。

    整份取数（不分页）的**整表档**。接口 16 的视图自 2026-11-19 起改走
    `prepare_idle_read()` ＋ `ResultPaginator` ＋ `IdleRead.rows()`，每请求只取回一页，
    **不经本函数**。现证消费口：`apps/assets/urls.py` 只注册了 `idle/`、接口 18 导出尚未落地
    ⇒ 眼下调用它的只有 `tests/test_idle_selectors.py` 与 `tests/test_seed_demo.py`；
    导出落地时它按 spec D14-h 就是导出的取数口。2026-11-19 下推取证的三臂对照显示这条整表档
    并没有变快（`new-full` 对 `old` median **0.969×**）：下推省的是 SQL 侧的筛与排，取回与建行
    仍按整份付。

    `idle_stopped_days` 每请求经 `get_platform_setting` 两级回退读取（spec US-4）。

    两条既定口径（接口 18 导出等后续消费方要照单继承）：

    - **归属优先级**：`resource_type == "domain"` 行的 `account_name` 取**注册商**
      （PRD 3.14-2），这就是产品规则本身，故域名行即便挂了 `cloud_account` 也显示注册商。
    - **排序全序性**：ORDER BY 已下推（`order_by_key()`）——非空桶的次级键 `pk` 跟随
      `sort_order`（`desc` 即 `pk DESC`），空值桶恒 `pk ASC` 且恒排最后。库里的行 `pk`
      非空且唯一 ⇒ 两个方向都是**严格全序**、跨请求稳定，逐页拼接不重不漏。

    Args:
        filters: 接口16 查询条件（已由序列化层校验）。`sort_field` 不在白名单时回退
            `expire_time`；`idle_types` 为空表示不按闲置类型筛。

    Returns:
        命中判据的 `IdleRow` 列表（资产 + `judge` 结论 + 已解析的归属账号名），
        整份返回、已按 SQL ORDER BY 排成严格全序；本函数不分页（分页只在视图层做）。
        无命中时为空列表。
    """
    read = prepare_idle_read(filters)
    return read.rows(list(read.queryset))
