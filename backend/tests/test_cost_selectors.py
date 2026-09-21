"""成本查询 selector 测试（接口1 汇总 / 接口2 明细 / 接口8 趋势）。

口径来自 PRD 2.2.1/2.2.2、api.md 接口 1/2/8、database.md（project_cost_daily.amount 已是 CNY，
查询期不再折算）。金额一律 Decimal；None 表示口径上的「--」，由序列化层翻译。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from apps.billing.models import CloudAccount, CloudBillDetail, ResourceTypeDict
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.cost.selectors import (
    CostQueryFilters,
    list_bill_details,
    query_cost_trend,
    summarize_project_costs,
)

# 本期 [2026-09-01, 2026-09-10]（L=10），比较区间 [2026-08-22, 2026-08-31]（previous_period）
CUR_START = date(2026, 9, 1)
CUR_END = date(2026, 9, 10)


@pytest.fixture
def account(db):
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-1",
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
    )


@pytest.fixture
def resource_types(db):
    # 清空 §5.2 种子（ecs/rds/eip/nat/domain），固定为本测试的列集合，保证断言确定性
    ResourceTypeDict.objects.all().delete()
    ResourceTypeDict.objects.create(code="ecs", display_name="云服务器", sort_order=1, enabled=True)
    ResourceTypeDict.objects.create(code="rds", display_name="数据库", sort_order=2, enabled=True)
    ResourceTypeDict.objects.create(
        code="oss", display_name="对象存储", sort_order=3, enabled=False
    )
    return ["ecs", "rds"]


def _daily(account, *, tag, status, rtype, amount, on=date(2026, 9, 1), region="cn-hz"):
    return ProjectCostDaily.objects.create(
        stat_date=on,
        project_tag=tag,
        tag_status=status,
        cloud_account=account,
        region=region,
        resource_type=rtype,
        amount=Decimal(str(amount)),
        bill_count=1,
    )


def _filters(**kw):
    base: dict[str, Any] = {"start": CUR_START, "end": CUR_END}
    base.update(kw)
    return CostQueryFilters(**base)


# ---------------------------------------------------------------- Cycle 1：列 + 行转列 + 合计


@pytest.mark.django_db
def test_resource_types_are_enabled_and_ordered(account, resource_types):
    result = summarize_project_costs(_filters())
    assert [rt["code"] for rt in result.resource_types] == ["ecs", "rds"]  # oss 停用被排除
    assert result.resource_types[0]["displayName"] == "云服务器"


@pytest.mark.django_db
def test_normal_project_row_pivots_by_resource_type(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projA", status="normal", rtype="rds", amount=50, on=date(2026, 9, 2))
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=200)

    result = summarize_project_costs(_filters())
    rows = {r.project_tag: r for r in result.rows}

    assert rows["projA"].amount_by_resource_type == {"ecs": Decimal("100"), "rds": Decimal("50")}
    assert rows["projA"].total_amount == Decimal("150")
    assert rows["projA"].tag_status == "normal"
    assert rows["projB"].total_amount == Decimal("200")
    # 未出现的资源类型补 0（F007）
    assert rows["projB"].amount_by_resource_type == {"ecs": Decimal("200"), "rds": Decimal("0")}


@pytest.mark.django_db
def test_summary_is_grand_total_across_rows(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projB", status="normal", rtype="rds", amount=200)

    result = summarize_project_costs(_filters())
    assert result.summary_total == Decimal("300")
    assert result.summary_amount_by_resource_type == {"ecs": Decimal("100"), "rds": Decimal("200")}


# ---------------------------------------------------------------- Cycle 2：比较区间 + 环比


@pytest.mark.django_db
def test_last_period_and_rate(account, resource_types):
    # 本期 [09-01,09-10] L=10 → 比较区间 [08-22,08-31]（PRD 2.2.1 等长前移）
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))
    _daily(account, tag="projA", status="normal", rtype="rds", amount=50, on=date(2026, 9, 2))
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=75, on=date(2026, 8, 25))

    result = summarize_project_costs(_filters())
    assert result.last_period_range == (date(2026, 8, 22), date(2026, 8, 31))
    row = next(r for r in result.rows if r.project_tag == "projA")
    assert row.total_amount == Decimal("150")
    assert row.last_period_amount == Decimal("75")
    assert row.rate == Decimal("100")  # (150-75)/75*100


@pytest.mark.django_db
def test_rate_none_when_no_previous_data(account, resource_types):
    _daily(account, tag="projNew", status="normal", rtype="ecs", amount=100)

    result = summarize_project_costs(_filters())
    row = next(r for r in result.rows if r.project_tag == "projNew")
    assert row.last_period_amount == Decimal("0")  # 无上期 → 0（F028）
    assert row.rate is None  # 上期为 0 → 环比 --（不除零）


# ---------------------------------------------------------------- Cycle 3：预算占比 / 超预算


def _budget(tag, month, amount):
    return ProjectBudget.objects.create(
        project_tag=tag, bill_month=month, budget_amount=Decimal(str(amount))
    )


@pytest.mark.django_db
def test_budget_configured_computes_rate(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150)
    _budget("projA", "2026-09", 300)

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "projA")
    assert row.budget_amount == Decimal("300")
    assert row.budget_rate == Decimal("50")  # 150/300*100
    assert row.over_budget is False
    assert row.budget_incomplete is False


@pytest.mark.django_db
def test_budget_over_budget_flag(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150)
    _budget("projA", "2026-09", 100)

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "projA")
    assert row.budget_rate == Decimal("150")  # 150/100*100
    assert row.over_budget is True  # 占比 > 100%


@pytest.mark.django_db
def test_budget_unconfigured_shows_none(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150)

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "projA")
    assert row.budget_amount is None  # 未配置预算 → --，不显示 0
    assert row.budget_rate is None
    assert row.over_budget is False  # 未配置不高亮（PRD 2.2.2）


@pytest.mark.django_db
def test_budget_partial_months_flag(account, resource_types):
    # 区间跨 2026-09 与 2026-10；仅配置 09 月预算 → 分母 >0 但有未配置月
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150, on=date(2026, 9, 1))
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150, on=date(2026, 10, 1))
    _budget("projA", "2026-09", 300)

    filters = _filters(start=date(2026, 9, 1), end=date(2026, 10, 5))
    row = next(r for r in summarize_project_costs(filters).rows if r.project_tag == "projA")
    assert row.total_amount == Decimal("300")
    assert row.budget_amount == Decimal("300")
    assert row.budget_rate == Decimal("100")  # 300/300*100
    assert row.budget_incomplete is True  # 部分账期月未配置预算


@pytest.mark.django_db
def test_budget_not_applied_to_unassigned(account, resource_types):
    _daily(account, tag="projX", status="unassigned", rtype="ecs", amount=150)
    _budget("projX", "2026-09", 100)  # 未分配成本恒不参与预算（PRD 2.2.2）

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "未分配成本")
    assert row.budget_amount is None
    assert row.budget_rate is None
    assert row.over_budget is False


# ---------------------------------------------------------------- Cycle 4：未分配成本归并


@pytest.mark.django_db
def test_unassigned_and_conflict_merge_into_one_row(account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=100)
    _daily(account, tag="projC", status="conflict", rtype="ecs", amount=50)
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=200)

    result = summarize_project_costs(_filters())
    unalloc = [r for r in result.rows if r.project_tag == "未分配成本"]
    assert len(unalloc) == 1  # unassigned + conflict 归并为单行
    assert unalloc[0].tag_status is None
    assert unalloc[0].total_amount == Decimal("150")
    assert unalloc[0].amount_by_resource_type == {"ecs": Decimal("150"), "rds": Decimal("0")}
    # normal 行不受影响
    assert next(r for r in result.rows if r.project_tag == "projB").tag_status == "normal"
    # 合计仍含未分配（NF010 守恒）
    assert result.summary_total == Decimal("350")


@pytest.mark.django_db
def test_unallocated_row_never_has_budget(account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=150)
    _budget("未分配成本", "2026-09", 100)  # 即便误配预算也不生效

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "未分配成本")
    assert row.budget_amount is None
    assert row.budget_rate is None
    assert row.over_budget is False


@pytest.mark.django_db
def test_unallocated_merge_spans_compare_period(account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=100, on=date(2026, 9, 1))
    _daily(account, tag="projD", status="conflict", rtype="ecs", amount=50, on=date(2026, 8, 25))

    row = next(r for r in summarize_project_costs(_filters()).rows if r.project_tag == "未分配成本")
    assert row.total_amount == Decimal("100")
    assert row.last_period_amount == Decimal("50")
    assert row.rate == Decimal("100")  # (100-50)/50*100


# ---------------------------------------------------------------- Cycle 5：筛选 + 全量排序


@pytest.fixture
def account2(db):
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-2",
        account_type=CloudAccount.AccountType.SUB,
        ak_cipher="x",
        sk_cipher="y",
    )


@pytest.mark.django_db
def test_filter_by_cloud_account(account, account2, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account2, tag="projA", status="normal", rtype="ecs", amount=40)

    result = summarize_project_costs(_filters(cloud_account_id=account.id))
    assert result.summary_total == Decimal("100")  # 仅 acc-1


@pytest.mark.django_db
def test_filter_by_resource_type(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projA", status="normal", rtype="rds", amount=50)

    result = summarize_project_costs(_filters(resource_type="rds"))
    row = next(r for r in result.rows if r.project_tag == "projA")
    assert row.amount_by_resource_type == {"ecs": Decimal("0"), "rds": Decimal("50")}
    assert row.total_amount == Decimal("50")


@pytest.mark.django_db
def test_filter_by_region(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, region="cn-hz")
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=40, region="cn-bj")

    result = summarize_project_costs(_filters(region="cn-bj"))
    assert result.summary_total == Decimal("40")


@pytest.mark.django_db
def test_filter_by_project_tag_exact(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=200)

    result = summarize_project_costs(_filters(project_tag="projA"))
    assert [r.project_tag for r in result.rows] == ["projA"]


@pytest.mark.django_db
def test_filter_by_keyword_fuzzy(account, resource_types):
    _daily(account, tag="projAlpha", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projBeta", status="normal", rtype="ecs", amount=200)

    result = summarize_project_costs(_filters(keyword="alpha"))
    assert [r.project_tag for r in result.rows] == ["projAlpha"]


@pytest.mark.django_db
def test_filter_by_unallocated_virtual_tag(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=70)

    result = summarize_project_costs(_filters(project_tag="未分配成本"))
    assert [r.project_tag for r in result.rows] == ["未分配成本"]
    assert result.summary_total == Decimal("70")


@pytest.mark.django_db
def test_default_sort_total_desc(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=300)
    _daily(account, tag="projC", status="normal", rtype="ecs", amount=200)

    result = summarize_project_costs(_filters())
    assert [r.project_tag for r in result.rows] == ["projB", "projC", "projA"]


@pytest.mark.django_db
def test_sort_by_project_tag_asc(account, resource_types):
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=300)
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)

    result = summarize_project_costs(_filters(sort_field="projectTag", sort_order="asc"))
    assert [r.project_tag for r in result.rows] == ["projA", "projB"]


@pytest.mark.django_db
def test_sort_total_asc(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=300)

    result = summarize_project_costs(_filters(sort_field="totalAmount", sort_order="asc"))
    assert [r.project_tag for r in result.rows] == ["projA", "projB"]


@pytest.mark.django_db
def test_sort_none_rate_goes_last(account, resource_types):
    # projA 有上期数据（rate 非空），projB 无上期（rate=None）→ None 恒排末尾
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=50, on=date(2026, 8, 25))
    _daily(account, tag="projB", status="normal", rtype="ecs", amount=999)

    result = summarize_project_costs(_filters(sort_field="rate", sort_order="desc"))
    assert result.rows[-1].project_tag == "projB"
    assert result.rows[-1].rate is None


# ---------------------------------------------------------------- 接口2：明细下钻 selector


def _bill(
    account,
    *,
    instance,
    rtype="ecs",
    region="cn-hz",
    charge="PostPaid",
    tag="projA",
    status="normal",
    amount_cny=100,
    on=date(2026, 9, 1),
):
    return CloudBillDetail.objects.create(
        cloud_account=account,
        region=region,
        instance_id=instance,
        resource_type=rtype,
        project_tag=tag,
        tag_status=status,
        charge_type=charge,
        currency="CNY",
        amount=Decimal(str(amount_cny)),
        amount_cny=Decimal(str(amount_cny)),
        bill_date=on,
        bill_month=f"{on.year:04d}-{on.month:02d}",
    )


@pytest.mark.django_db
def test_detail_aggregates_per_instance_over_range(account, resource_types):
    _bill(account, instance="i-1", amount_cny=100, on=date(2026, 9, 1))
    _bill(account, instance="i-1", amount_cny=50, on=date(2026, 9, 2))
    _bill(account, instance="i-2", amount_cny=30)

    rows = list(list_bill_details(_filters()))
    assert len(rows) == 2  # 同实例跨日合并为一行（PRD 3.6 无日期列）
    by_inst = {r["instance_id"]: r for r in rows}
    assert by_inst["i-1"]["amount"] == Decimal("150")
    assert by_inst["i-2"]["amount"] == Decimal("30")


@pytest.mark.django_db
def test_detail_row_exposes_expected_fields(account, resource_types):
    _bill(account, instance="i-1", rtype="ecs", region="cn-hz", charge="PostPaid")

    row = list_bill_details(_filters())[0]
    assert row["instance_id"] == "i-1"
    assert row["resource_type"] == "ecs"
    assert row["region"] == "cn-hz"
    assert row["charge_type"] == "PostPaid"
    assert row["tag_status"] == "normal"
    assert row["cloud_account__account_name"] == "acc-1"


@pytest.mark.django_db
def test_detail_respects_date_range(account, resource_types):
    _bill(account, instance="i-1", amount_cny=100, on=date(2026, 9, 1))
    _bill(account, instance="i-2", amount_cny=999, on=date(2026, 7, 1))  # 区间外

    rows = list(list_bill_details(_filters()))
    assert [r["instance_id"] for r in rows] == ["i-1"]


@pytest.mark.django_db
def test_detail_filter_by_project_tag(account, resource_types):
    _bill(account, instance="i-1", tag="projA")
    _bill(account, instance="i-2", tag="projB")

    rows = list(list_bill_details(_filters(project_tag="projA")))
    assert [r["instance_id"] for r in rows] == ["i-1"]


@pytest.mark.django_db
def test_detail_filter_by_tag_status(account, resource_types):
    _bill(account, instance="i-1", tag="projA", status="normal")
    _bill(account, instance="i-2", tag="", status="unassigned")
    _bill(account, instance="i-3", tag="projC", status="conflict")

    rows = list(list_bill_details(_filters(tag_status="unassigned")))
    assert [r["instance_id"] for r in rows] == ["i-2"]


@pytest.mark.django_db
def test_detail_filter_unallocated_virtual_tag(account, resource_types):
    _bill(account, instance="i-1", tag="projA", status="normal")
    _bill(account, instance="i-2", tag="", status="unassigned")
    _bill(account, instance="i-3", tag="projC", status="conflict")

    rows = list(list_bill_details(_filters(project_tag="未分配成本")))
    assert sorted(r["instance_id"] for r in rows) == ["i-2", "i-3"]


@pytest.mark.django_db
def test_detail_filter_by_resource_type_and_region(account, resource_types):
    _bill(account, instance="i-1", rtype="ecs", region="cn-hz")
    _bill(account, instance="i-2", rtype="rds", region="cn-hz")
    _bill(account, instance="i-3", rtype="ecs", region="cn-bj")

    rows = list(list_bill_details(_filters(resource_type="ecs", region="cn-hz")))
    assert [r["instance_id"] for r in rows] == ["i-1"]


@pytest.mark.django_db
def test_detail_filter_by_cloud_account(account, account2, resource_types):
    _bill(account, instance="i-1")
    _bill(account2, instance="i-2")

    rows = list(list_bill_details(_filters(cloud_account_id=account.id)))
    assert [r["instance_id"] for r in rows] == ["i-1"]


@pytest.mark.django_db
def test_detail_default_sort_amount_desc(account, resource_types):
    _bill(account, instance="i-1", amount_cny=100)
    _bill(account, instance="i-2", amount_cny=300)
    _bill(account, instance="i-3", amount_cny=200)

    rows = list(list_bill_details(_filters()))
    assert [r["instance_id"] for r in rows] == ["i-2", "i-3", "i-1"]


@pytest.mark.django_db
def test_detail_sort_by_instance_asc(account, resource_types):
    _bill(account, instance="i-2")
    _bill(account, instance="i-1")

    rows = list(list_bill_details(_filters(sort_field="instanceId", sort_order="asc")))
    assert [r["instance_id"] for r in rows] == ["i-1", "i-2"]


# ---------------------------------------------------------------- 接口8：成本趋势 selector

TODAY = date(2026, 9, 21)  # 注入「今天」，保证含预估判定确定性


def _trend(**kw):
    return query_cost_trend(_filters(**kw), today=TODAY)


@pytest.mark.django_db
def test_trend_current_series_is_continuous_daily(account, resource_types):
    # 区间 09-01~09-03，仅 09-01 有数据 → 仍返回 3 个连续日点（缺日 items 为空）
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))

    result = _trend(start=date(2026, 9, 1), end=date(2026, 9, 3))
    assert [p.date for p in result.current] == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]
    assert result.current[0].items  # 09-01 有项
    assert result.current[1].items == []  # 09-02 无数据
    assert result.current[2].items == []


@pytest.mark.django_db
def test_trend_point_items_per_project(account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))
    _daily(account, tag="projB", status="normal", rtype="rds", amount=50, on=date(2026, 9, 1))

    point = _trend(start=date(2026, 9, 1), end=date(2026, 9, 1)).current[0]
    amounts = {i.project_tag: i.amount for i in point.items}
    assert amounts == {"projA": Decimal("100"), "projB": Decimal("50")}
    assert all(i.tag_status == "normal" for i in point.items)


@pytest.mark.django_db
def test_trend_merges_unallocated(account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=70, on=date(2026, 9, 1))
    _daily(account, tag="projC", status="conflict", rtype="ecs", amount=30, on=date(2026, 9, 1))

    point = _trend(start=date(2026, 9, 1), end=date(2026, 9, 1)).current[0]
    assert len(point.items) == 1
    assert point.items[0].project_tag == "未分配成本"
    assert point.items[0].tag_status is None
    assert point.items[0].amount == Decimal("100")


@pytest.mark.django_db
def test_trend_compare_range_and_series(account, resource_types):
    # 本期 [09-01,09-10] L=10 → 比较区间 [08-22,08-31]
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=55, on=date(2026, 8, 25))

    result = _trend()
    assert result.compare_range == (date(2026, 8, 22), date(2026, 8, 31))
    assert len(result.compare) == 10  # 等长连续日点
    day = next(p for p in result.compare if p.date == date(2026, 8, 25))
    assert day.items[0].amount == Decimal("55")


@pytest.mark.django_db
def test_trend_filters_apply(account, account2, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))
    _daily(account2, tag="projA", status="normal", rtype="ecs", amount=40, on=date(2026, 9, 1))

    result = _trend(start=date(2026, 9, 1), end=date(2026, 9, 1), cloud_account_id=account.id)
    assert result.current[0].items[0].amount == Decimal("100")


@pytest.mark.django_db
def test_trend_bill_month_incomplete_true_for_current_month(account, resource_types):
    # 区间覆盖 today(2026-09) 所在月 → 含预估
    result = _trend(start=date(2026, 9, 1), end=date(2026, 9, 10))
    assert result.bill_month_incomplete is True


@pytest.mark.django_db
def test_trend_bill_month_incomplete_false_for_past_month(account, resource_types):
    # 区间为已出账的历史月（2026-08），today 在 09 月 → 不含预估
    result = _trend(start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert result.bill_month_incomplete is False
