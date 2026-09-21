"""成本查询读路径（engineering-conventions §2：selectors 只做读，不含写）。

数据源：
- 汇总/趋势读 ``project_cost_daily``（天粒度预聚合，``amount`` 已是 CNY——账单入库时折算，
  见 database.md 表 2/4 与 PRD 2.3，查询期不再乘汇率）；
- 明细读 ``cloud_bill_detail``（分区表，取 ``amount_cny``）。

口径复用 ``apps/cost/services.py`` 纯函数（环比 previous_period/mom_change_pct、
预算 budget_denominator/budget_ratio_pct）。金额一律 Decimal；``None`` 表示口径上的「--」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import QuerySet, Sum

from apps.billing.models import CloudBillDetail, ResourceTypeDict
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.cost.services import (
    TAG_CONFLICT,
    TAG_NORMAL,
    TAG_UNASSIGNED,
    budget_denominator,
    budget_ratio_pct,
    covered_bill_months,
    mom_change_pct,
    previous_period,
)

# 未分配成本虚拟分类（PRD 术语表：不是真实项目标签；unassigned+conflict 归并到此）
UNALLOCATED_LABEL = "未分配成本"


@dataclass(frozen=True)
class CostQueryFilters:
    """三接口共用的查询条件（已由序列化层校验）。"""

    start: date
    end: date
    project_tag: str | None = None
    resource_type: str | None = None
    cloud_account_id: int | None = None
    region: str | None = None
    keyword: str | None = None
    tag_status: str | None = None
    sort_field: str = "totalAmount"
    sort_order: str = "desc"


@dataclass(frozen=True)
class SummaryRow:
    project_tag: str
    tag_status: str | None
    amount_by_resource_type: dict[str, Decimal]
    total_amount: Decimal
    last_period_amount: Decimal | None = None
    rate: Decimal | None = None
    budget_amount: Decimal | None = None
    budget_rate: Decimal | None = None
    over_budget: bool = False
    budget_incomplete: bool = False


@dataclass(frozen=True)
class SummaryResult:
    resource_types: list[dict[str, str]]
    rows: list[SummaryRow]
    summary_amount_by_resource_type: dict[str, Decimal]
    summary_total: Decimal
    stat_range: tuple[date, date]
    last_period_range: tuple[date, date]


def _row_key(tag: str, status: str) -> tuple[str, str | None]:
    """归并行键：normal 保留真实标签；unassigned/conflict 归并到虚拟「未分配成本」。"""
    if status == TAG_NORMAL:
        return tag, TAG_NORMAL
    return UNALLOCATED_LABEL, None


# sortField（api.md 接口1 camelCase）→ SummaryRow 属性
SORT_FIELDS = {
    "projectTag": "project_tag",
    "totalAmount": "total_amount",
    "lastPeriodAmount": "last_period_amount",
    "rate": "rate",
    "budgetAmount": "budget_amount",
    "budgetRate": "budget_rate",
}


def _apply_filters(qs, filters: CostQueryFilters):
    """维度筛选（与日期无关，本期/比较区间共用）。projectTag 支持「未分配成本」虚拟项。"""
    if filters.cloud_account_id is not None:
        qs = qs.filter(cloud_account_id=filters.cloud_account_id)
    if filters.region:
        qs = qs.filter(region=filters.region)
    if filters.resource_type:
        qs = qs.filter(resource_type=filters.resource_type)
    if filters.project_tag:
        if filters.project_tag == UNALLOCATED_LABEL:
            qs = qs.filter(tag_status__in=[TAG_UNASSIGNED, TAG_CONFLICT])
        else:
            qs = qs.filter(project_tag=filters.project_tag, tag_status=TAG_NORMAL)
    if filters.keyword:
        qs = qs.filter(project_tag__icontains=filters.keyword)
    return qs


def _aggregate_period(
    filters: CostQueryFilters, start: date, end: date
) -> dict[tuple[str, str | None], dict[str, Decimal]]:
    """按归并行键分桶，桶内按 resource_type 汇总金额。"""
    qs = ProjectCostDaily.objects.filter(stat_date__gte=start, stat_date__lte=end)
    qs = _apply_filters(qs, filters)
    agg = qs.values("project_tag", "tag_status", "resource_type").annotate(total=Sum("amount"))
    out: dict[tuple[str, str | None], dict[str, Decimal]] = {}
    for row in agg:
        key = _row_key(row["project_tag"], row["tag_status"])
        bucket = out.setdefault(key, {})
        rtype = row["resource_type"]
        bucket[rtype] = bucket.get(rtype, Decimal(0)) + (row["total"] or Decimal(0))
    return out


def _sort_rows(rows: list[SummaryRow], sort_field: str, sort_order: str) -> list[SummaryRow]:
    """在全量结果上排序（api.md 接口1：先聚合→排序→分页）。

    可空数值列（rate/budgetAmount/budgetRate）的 None（``--``）恒排末尾，不随升降序翻转；
    同值以 project_tag 兜底保证确定性。
    """
    attr = SORT_FIELDS.get(sort_field, "total_amount")
    reverse = sort_order != "asc"
    with_val = [r for r in rows if getattr(r, attr) is not None]
    without_val = [r for r in rows if getattr(r, attr) is None]
    with_val.sort(key=lambda r: (getattr(r, attr), r.project_tag), reverse=reverse)
    without_val.sort(key=lambda r: r.project_tag)
    return with_val + without_val


def summarize_project_costs(filters: CostQueryFilters) -> SummaryResult:
    """接口1：项目维度汇总（含资源类型行转列、全量合计）。"""
    compare_start, compare_end = previous_period(filters.start, filters.end)

    rt_rows = list(ResourceTypeDict.objects.filter(enabled=True).order_by("sort_order", "code"))
    resource_types = [{"code": r.code, "displayName": r.display_name} for r in rt_rows]
    rt_codes = [r.code for r in rt_rows]

    current = _aggregate_period(filters, filters.start, filters.end)
    prev = _aggregate_period(filters, compare_start, compare_end)

    budgets_by_tag = _budgets_by_tag(current, filters.start, filters.end)

    rows: list[SummaryRow] = []
    summary_by_rt = {code: Decimal(0) for code in rt_codes}
    summary_total = Decimal(0)
    for (tag, status), by_rt in current.items():
        pivot = {code: by_rt.get(code, Decimal(0)) for code in rt_codes}
        total = sum(by_rt.values(), Decimal(0))
        # 上期同桶合计；无上期数据记 0（F028），mom_change_pct 遇 0 自动降级 --
        last_total = sum(prev.get((tag, status), {}).values(), Decimal(0))
        budget_amount, budget_rate, over_budget, budget_incomplete = _budget_fields(
            tag, status, total, budgets_by_tag, filters.start, filters.end
        )
        rows.append(
            SummaryRow(
                project_tag=tag,
                tag_status=status,
                amount_by_resource_type=pivot,
                total_amount=total,
                last_period_amount=last_total,
                rate=mom_change_pct(total, last_total),
                budget_amount=budget_amount,
                budget_rate=budget_rate,
                over_budget=over_budget,
                budget_incomplete=budget_incomplete,
            )
        )
        for code in rt_codes:
            summary_by_rt[code] += pivot[code]
        summary_total += total

    rows = _sort_rows(rows, filters.sort_field, filters.sort_order)

    return SummaryResult(
        resource_types=resource_types,
        rows=rows,
        summary_amount_by_resource_type=summary_by_rt,
        summary_total=summary_total,
        stat_range=(filters.start, filters.end),
        last_period_range=(compare_start, compare_end),
    )


def _budgets_by_tag(
    current: dict[tuple[str, str | None], dict[str, Decimal]], start: date, end: date
) -> dict[str, dict[str, Decimal]]:
    """取本期各正常项目在所覆盖账期月上的预算，映射 tag → {账期月: 金额}（PRD 2.2.2）。"""
    tags = {tag for (tag, status) in current if status == TAG_NORMAL}
    if not tags:
        return {}
    months = covered_bill_months(start, end)
    out: dict[str, dict[str, Decimal]] = {}
    qs = ProjectBudget.objects.filter(project_tag__in=tags, bill_month__in=months)
    for b in qs:
        out.setdefault(b.project_tag, {})[b.bill_month] = b.budget_amount
    return out


def _budget_fields(
    tag: str,
    status: str | None,
    total: Decimal,
    budgets_by_tag: dict[str, dict[str, Decimal]],
    start: date,
    end: date,
) -> tuple[Decimal | None, Decimal | None, bool, bool]:
    """单行预算四元组 (budget_amount, budget_rate, over_budget, budget_incomplete)。

    仅 normal 行参与预算；未分配/冲突恒无预算（PRD 2.2.2）。分母为 0 → 未配置，
    金额与占比记 None（``--``），不高亮超预算。
    """
    if status != TAG_NORMAL:
        return None, None, False, False
    denom = budget_denominator(budgets_by_tag.get(tag, {}), start, end)
    if not denom.is_configured:
        return None, None, False, False
    rate = budget_ratio_pct(total, denom.total)
    return denom.total, rate, rate is not None and rate > 100, denom.partially_unconfigured


# ---------- 接口2：项目资源明细下钻（读 cloud_bill_detail，金额取 amount_cny） ----------

# sortField（api.md 接口2 camelCase）→ 聚合查询可排序键
DETAIL_SORT_FIELDS = {
    "instanceId": "instance_id",
    "resourceType": "resource_type",
    "cloudAccountName": "cloud_account__account_name",
    "region": "region",
    "chargeType": "charge_type",
    "amount": "amount",
}


def list_bill_details(filters: CostQueryFilters) -> QuerySet:
    """接口2：实例维度明细，按区间将同实例账单聚合为一行（PRD 3.6 子表无日期列）。

    返回 values+annotate 查询集（金额 = ``Sum(amount_cny)``，已是 CNY），由视图层分页（单页 ≤100）；
    排序在全量查询集上执行。实例ID 的角色屏蔽在序列化层统一处理（permissions.md），不在此层。
    """
    qs = CloudBillDetail.objects.filter(bill_date__gte=filters.start, bill_date__lte=filters.end)
    if filters.cloud_account_id is not None:
        qs = qs.filter(cloud_account_id=filters.cloud_account_id)
    if filters.region:
        qs = qs.filter(region=filters.region)
    if filters.resource_type:
        qs = qs.filter(resource_type=filters.resource_type)
    if filters.tag_status:
        qs = qs.filter(tag_status=filters.tag_status)
    if filters.project_tag:
        if filters.project_tag == UNALLOCATED_LABEL:
            qs = qs.filter(tag_status__in=[TAG_UNASSIGNED, TAG_CONFLICT])
        else:
            qs = qs.filter(project_tag=filters.project_tag)

    agg = qs.values(
        "instance_id",
        "resource_type",
        "cloud_account__account_name",
        "region",
        "charge_type",
        "tag_status",
    ).annotate(amount=Sum("amount_cny"))

    sort_key = DETAIL_SORT_FIELDS.get(filters.sort_field, "amount")
    prefix = "-" if filters.sort_order != "asc" else ""
    # 次级按 instance_id 兜底，保证分页稳定（同额/同值不跳行）
    return agg.order_by(f"{prefix}{sort_key}", "instance_id")


# ---------- 接口8：成本趋势（逐日序列 + 比较区间，复用 _apply_filters/_row_key） ----------


@dataclass(frozen=True)
class TrendItem:
    project_tag: str
    tag_status: str | None
    amount: Decimal


@dataclass(frozen=True)
class TrendPoint:
    date: date
    items: list[TrendItem]


@dataclass(frozen=True)
class TrendResult:
    current: list[TrendPoint]
    compare: list[TrendPoint]
    stat_range: tuple[date, date]
    compare_range: tuple[date, date]
    bill_month_incomplete: bool


def _daily_series(filters: CostQueryFilters, start: date, end: date) -> list[TrendPoint]:
    """按 stat_date + 归并行键聚合金额，补齐区间内每个日历日（缺日 items 为空）。"""
    qs = ProjectCostDaily.objects.filter(stat_date__gte=start, stat_date__lte=end)
    qs = _apply_filters(qs, filters)
    agg = qs.values("stat_date", "project_tag", "tag_status").annotate(total=Sum("amount"))

    by_date: dict[date, dict[tuple[str, str | None], Decimal]] = {}
    for row in agg:
        key = _row_key(row["project_tag"], row["tag_status"])
        day = by_date.setdefault(row["stat_date"], {})
        day[key] = day.get(key, Decimal(0)) + (row["total"] or Decimal(0))

    points: list[TrendPoint] = []
    cur = start
    while cur <= end:
        buckets = by_date.get(cur, {})
        items = [
            TrendItem(tag, status, amount)
            for (tag, status), amount in sorted(buckets.items(), key=lambda kv: kv[0][0])
        ]
        points.append(TrendPoint(cur, items))
        cur += timedelta(days=1)
    return points


def query_cost_trend(filters: CostQueryFilters, *, today: date | None = None) -> TrendResult:
    """接口8：本期 + 比较区间逐日序列。

    比较区间为 PRD 2.2.1 等长前移区间；unassigned/conflict 归并为「未分配成本」。
    ``bill_month_incomplete``：本期覆盖到「今天」所在自然月即标记含预估（PRD 2.1.2
    「未出账账期通常为当月」）。``today`` 可注入以便测试，默认取系统当日。
    """
    today = today or date.today()
    compare_start, compare_end = previous_period(filters.start, filters.end)
    this_month = f"{today.year:04d}-{today.month:02d}"
    incomplete = this_month in covered_bill_months(filters.start, filters.end)
    return TrendResult(
        current=_daily_series(filters, filters.start, filters.end),
        compare=_daily_series(filters, compare_start, compare_end),
        stat_range=(filters.start, filters.end),
        compare_range=(compare_start, compare_end),
        bill_month_incomplete=incomplete,
    )
