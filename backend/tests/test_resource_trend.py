"""仪表盘趋势按 resource_type 分组测试（api.md 接口9 trend，复用接口8 结构）。

接口8 的趋势按项目标签归并；仪表盘趋势图按**资源类型**堆叠（PRD 3.10-2，
groupBy=resource_type），复用同一 TrendResult 结构与等长前移比较区间口径。
TrendItem.project_tag 承载资源类型码、tag_status 恒 None（由序列化层映射为 resourceType）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.billing.models import CloudAccount
from apps.cost.models import ProjectCostDaily
from apps.cost.selectors import CostQueryFilters, query_resource_trend

TODAY = date(2026, 9, 21)


def _cost(stat_date: date, resource_type: str, amount: str, account: CloudAccount) -> None:
    ProjectCostDaily.objects.create(
        stat_date=stat_date,
        project_tag="projA",
        tag_status=ProjectCostDaily.TagStatus.NORMAL,
        cloud_account=account,
        region="cn-hangzhou",
        resource_type=resource_type,
        amount=Decimal(amount),
        bill_count=1,
    )


@pytest.fixture
def seeded(db):
    acc = CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-1",
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
    )
    # 本期 [09-20, 09-21]
    _cost(date(2026, 9, 20), "ecs", "100", acc)
    _cost(date(2026, 9, 20), "rds", "50", acc)
    _cost(date(2026, 9, 21), "ecs", "30", acc)
    # 比较区间等长前移 [09-18, 09-19]
    _cost(date(2026, 9, 18), "ecs", "10", acc)
    return acc


def _filters(start: date, end: date) -> CostQueryFilters:
    return CostQueryFilters(start=start, end=end)


@pytest.mark.django_db
def test_resource_trend_groups_by_resource_type(seeded):
    result = query_resource_trend(_filters(date(2026, 9, 20), date(2026, 9, 21)), today=TODAY)

    assert [p.date for p in result.current] == [date(2026, 9, 20), date(2026, 9, 21)]
    day1 = {(i.project_tag, i.tag_status): i.amount for i in result.current[0].items}
    # 按资源类型堆叠：ecs 100、rds 50，tag_status 恒 None
    assert day1 == {("ecs", None): Decimal("100"), ("rds", None): Decimal("50")}
    day2 = {(i.project_tag, i.tag_status): i.amount for i in result.current[1].items}
    assert day2 == {("ecs", None): Decimal("30")}


@pytest.mark.django_db
def test_resource_trend_compare_is_equal_length_previous(seeded):
    result = query_resource_trend(_filters(date(2026, 9, 20), date(2026, 9, 21)), today=TODAY)

    assert result.compare_range == (date(2026, 9, 18), date(2026, 9, 19))
    cmp_day1 = {(i.project_tag): i.amount for i in result.compare[0].items}
    assert cmp_day1 == {"ecs": Decimal("10")}
    assert result.compare[1].items == []  # 09-19 无数据，补空


@pytest.mark.django_db
def test_resource_trend_marks_current_month_incomplete(seeded):
    result = query_resource_trend(_filters(date(2026, 9, 20), date(2026, 9, 21)), today=TODAY)
    assert result.bill_month_incomplete is True  # 覆盖到当月，含预估
