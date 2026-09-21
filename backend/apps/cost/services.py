"""口径计算层（engineering-conventions §5.3）+ 预聚合覆盖写（§6 uk_daily）。

口径计算覆盖 PRD 2.1.1 标签归属、2.2.1 环比、2.2.2 预算分母与占比、2.4 除零/--
降级，全部为无副作用纯函数。「可追溯、可复算」（PRD 1.2-6）的唯一实现：
账单导入（apps/billing/services.py）与聚合任务共享本模块的标签归属规则，
环比与预算占比不落库、查询时计算。

``overwrite_daily`` 是唯一的写路径函数（§6）：聚合任务整日全量重算后覆盖写。

金额链路一律 Decimal（§3 金额红线）；展示层格式化（千分位两位小数）不在此层。
返回 ``None`` 即口径上的「--」（无法计算），由序列化层翻译，禁止用 0 冒充。
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from apps.billing.models import CloudBillDetail
from apps.cost.models import ProjectCostDaily

TAG_NORMAL = ProjectCostDaily.TagStatus.NORMAL
TAG_UNASSIGNED = ProjectCostDaily.TagStatus.UNASSIGNED
TAG_CONFLICT = ProjectCostDaily.TagStatus.CONFLICT


# ---------- 标签归属（PRD 2.1.1） ----------


@dataclass(frozen=True)
class TagOwnership:
    """标签归属判定结果：status + 归属标签值。"""

    tag_status: str
    # normal：唯一有效标签值；unassigned：None；conflict：首个标签值（治理定位用，
    # 完整冲突值见 raw_conflict_values，原始标签串由调用方落 raw_tags 保留）
    project_tag: str | None
    raw_conflict_values: tuple[str, ...] = ()

    @property
    def is_normal(self) -> bool:
        return self.tag_status == TAG_NORMAL


def resolve_tag_ownership(values: Sequence[str | None]) -> TagOwnership:
    """按 PRD 2.1.1 判定标签归属。

    恰 1 个非空项目标签 → normal；0 个 → unassigned；≥2 个 → conflict
    （不做静默取其一参与归集，也不做成本分摊——分摊算法留二期）。
    ``values`` 为资源上键名为 ``project``（键名可配置）的标签值集合。
    """
    cleaned = [v.strip() for v in values if v is not None and v.strip()]
    if len(cleaned) == 1:
        return TagOwnership(TAG_NORMAL, cleaned[0])
    if not cleaned:
        return TagOwnership(TAG_UNASSIGNED, None)
    return TagOwnership(TAG_CONFLICT, cleaned[0], tuple(cleaned))


# ---------- 环比（PRD 2.2.1） ----------


def previous_period(start: date, end: date) -> tuple[date, date]:
    """上期区间 = [D1 - L, D1 - 1]（紧邻本期起点之前的等长区间，L = D2 - D1 + 1）。"""
    if end < start:
        raise ValueError(f"区间非法：end {end} 早于 start {start}")
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def mom_change_pct(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    """环比变动 = (本期 - 上期) ÷ 上期 × 100%。

    上期为 0、负值或不存在（None）→ 返回 None（展示 ``--``，不除零，PRD 2.2.1-3）。
    负金额正常参与计算（PRD 2.1.2-4），本期为 None 视为账单未同步，同样降级 ``--``。
    """
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous * Decimal(100)


# ---------- 预算分母与占比（PRD 2.2.2） ----------


def covered_bill_months(start: date, end: date) -> list[str]:
    """查询区间覆盖的账期月（YYYY-MM），含仅部分覆盖的月（PRD 2.2.2-2）。"""
    if end < start:
        raise ValueError(f"区间非法：end {end} 早于 start {start}")
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


@dataclass(frozen=True)
class BudgetDenominator:
    """预算分母计算结果（PRD 2.2.2-2/3）。"""

    months: tuple[str, ...]
    # 金额 > 0 的账期月（金额为 0 视为未配置，同缺失处理）
    configured_months: tuple[str, ...]
    unconfigured_months: tuple[str, ...]
    total: Decimal

    @property
    def is_configured(self) -> bool:
        """分母为 0 → 判定「未配置预算」，占比展示 --、不参与超预算高亮。"""
        return self.total > 0

    @property
    def partially_unconfigured(self) -> bool:
        """分母 > 0 但存在未配置月 → 页面标注「部分账期月未配置预算」。"""
        return self.total > 0 and bool(self.unconfigured_months)


def budget_denominator(
    budgets: Mapping[str, Decimal | None], start: date, end: date
) -> BudgetDenominator:
    """分母 = 所覆盖各账期月预算之和；未配置（缺失或金额 0）按 0 计入。

    ``budgets`` 为 账期月 → 预算金额 的映射，由查询层从 project_budget 取出后传入，
    保证本函数纯度（预算不冗余、展示时 join，PRD 2.2.2-1/5）。
    """
    months = tuple(covered_bill_months(start, end))
    configured: list[str] = []
    total = Decimal(0)
    for month in months:
        amount = budgets.get(month)
        if amount is not None and amount > 0:
            configured.append(month)
            total += amount
    unconfigured = tuple(m for m in months if m not in configured)
    return BudgetDenominator(months, tuple(configured), unconfigured, total)


def budget_ratio_pct(current: Decimal | None, denominator: Decimal) -> Decimal | None:
    """预算占比 = 本期项目总支出 ÷ 预算分母 × 100%。

    分母 ≤ 0（未配置预算）→ None（``--``，不参与超预算高亮）。
    占比 > 100 由调用方判定高亮；「未分配成本」与「标签冲突」不调用本函数（恒无预算）。
    """
    if current is None or denominator <= 0:
        return None
    return current / denominator * Decimal(100)


# ---------- 预聚合覆盖写（§6 uk_daily，唯一写路径函数） ----------


def _daily_key(row: ProjectCostDaily) -> tuple[date, str, str, int, str | None, str]:
    return (
        row.stat_date,
        row.project_tag,
        row.tag_status,
        row.cloud_account_id,
        row.region,
        row.resource_type,
    )


def overwrite_daily(rows: Iterable[ProjectCostDaily]) -> tuple[int, int]:
    """uk_daily 覆盖写：按受影响 ``stat_date`` 集合同事务 DELETE + INSERT。

    聚合任务按天全量重算后整批写入——天是最小覆盖粒度，不按维度局部 UPDATE，
    重复聚合不产生重复金额（测试用例 152-7）。同批内重复键取后者。
    返回 (deleted, inserted)。
    """
    deduped = {_daily_key(row): row for row in rows}
    objs = list(deduped.values())
    if not objs:
        return 0, 0
    dates = {row.stat_date for row in objs}
    with transaction.atomic():
        deleted, _ = ProjectCostDaily.objects.filter(stat_date__in=dates).delete()
        ProjectCostDaily.objects.bulk_create(objs)
    return deleted, len(objs)


def aggregate_daily(start: date, end: date) -> tuple[int, int]:
    """任务2：把 ``[start, end]`` 账单按六键聚合为日成本，覆盖写 ``project_cost_daily``。

    分组键 = stat_date(bill_date) + project_tag + tag_status + cloud_account + region
    + resource_type（tasks.md 任务2）；标签归属已在账单入库时落定（build_bill_row），
    此处直接信任，不再重算。金额取 ``Sum(amount_cny)``（账单入库已折算为 CNY）。

    unassigned 的 ``project_tag`` 为 None → 归一为 ``""``（``ProjectCostDaily.project_tag``
    列非空；查询层按 tag_status 归并到「未分配成本」，该值仅作占位）。整组 ``amount_cny``
    全为 NULL（缺汇率未折算）→ 跳过不生成行，待汇率补录后重算窗口拾回，不以 0 冒充。

    返回 ``overwrite_daily`` 的 ``(deleted, inserted)``。
    """
    agg = (
        CloudBillDetail.objects.filter(bill_date__gte=start, bill_date__lte=end)
        .values(
            "bill_date",
            "project_tag",
            "tag_status",
            "cloud_account_id",
            "region",
            "resource_type",
        )
        .annotate(total=Sum("amount_cny"), cnt=Count("id"))
    )
    rows: list[ProjectCostDaily] = []
    for g in agg:
        if g["total"] is None:
            continue
        rows.append(
            ProjectCostDaily(
                stat_date=g["bill_date"],
                project_tag=g["project_tag"] or "",
                tag_status=g["tag_status"],
                cloud_account_id=g["cloud_account_id"],
                region=g["region"],
                resource_type=g["resource_type"],
                amount=g["total"],
                bill_count=g["cnt"],
            )
        )
    return overwrite_daily(rows)
