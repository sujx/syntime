"""成本预聚合任务测试（tasks.md 任务2）：账单 → project_cost_daily 覆盖写。

口径：按【stat_date + project_tag + tag_status + cloud_account + region + resource_type】
分组求和 amount_cny；标签归属已在账单入库时落定（build_bill_row），聚合直接信任；
unassigned 的 project_tag 为 None → 归一为 ""（uk_daily nulls_distinct=False，但模型列非空）；
写入复用 services.overwrite_daily（按受影响 stat_date 同事务 DELETE+INSERT，不增量累加）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.billing.models import CloudAccount, CloudBillDetail
from apps.cost.models import ProjectCostDaily
from apps.cost.services import aggregate_daily

NORMAL = ProjectCostDaily.TagStatus.NORMAL
UNASSIGNED = ProjectCostDaily.TagStatus.UNASSIGNED
CONFLICT = ProjectCostDaily.TagStatus.CONFLICT


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
def account2(db):
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-2",
        account_type=CloudAccount.AccountType.SUB,
        ak_cipher="x",
        sk_cipher="y",
    )


_seq = 0


def _bill(
    account,
    *,
    rtype="ecs",
    tag="projA",
    status=NORMAL,
    region="cn-hz",
    amount_cny=100,
    on=date(2026, 9, 1),
    charge="PostPaid",
):
    global _seq
    _seq += 1
    return CloudBillDetail.objects.create(
        cloud_account=account,
        region=region,
        instance_id=f"i-{_seq}",
        resource_type=rtype,
        project_tag=tag,
        tag_status=status,
        charge_type=charge,
        currency="CNY",
        amount=Decimal(str(100 if amount_cny is None else amount_cny)),
        amount_cny=None if amount_cny is None else Decimal(str(amount_cny)),
        bill_date=on,
        bill_month=f"{on.year:04d}-{on.month:02d}",
    )


def _daily_rows(**kw):
    return ProjectCostDaily.objects.filter(**kw)


@pytest.mark.django_db
def test_groups_by_six_keys_and_sums(account):
    _bill(account, rtype="ecs", amount_cny=100)
    _bill(account, rtype="ecs", amount_cny=50)
    _bill(account, rtype="rds", amount_cny=30)

    deleted, inserted = aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert inserted == 2  # ecs 组合并、rds 一组
    rows = {r.resource_type: r for r in _daily_rows()}
    assert rows["ecs"].amount == Decimal("150")
    assert rows["ecs"].bill_count == 2
    assert rows["rds"].amount == Decimal("30")
    assert rows["rds"].bill_count == 1
    assert rows["ecs"].stat_date == date(2026, 9, 1)
    assert rows["ecs"].project_tag == "projA"
    assert rows["ecs"].tag_status == NORMAL


@pytest.mark.django_db
def test_separates_by_account_region_and_status(account, account2):
    _bill(account, region="cn-hz", amount_cny=100)
    _bill(account2, region="cn-hz", amount_cny=40)
    _bill(account, region="cn-bj", amount_cny=20)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert _daily_rows().count() == 3


@pytest.mark.django_db
def test_unassigned_project_tag_normalized_to_empty(account):
    _bill(account, tag=None, status=UNASSIGNED, amount_cny=70)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    row = _daily_rows().get()
    assert row.project_tag == ""  # None → ""（模型列非空）
    assert row.tag_status == UNASSIGNED
    assert row.amount == Decimal("70")


@pytest.mark.django_db
def test_conflict_keeps_first_tag_value(account):
    _bill(account, tag="projC", status=CONFLICT, amount_cny=55)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    row = _daily_rows().get()
    assert row.tag_status == CONFLICT
    assert row.project_tag == "projC"


@pytest.mark.django_db
def test_rerun_is_idempotent_no_double_count(account):
    _bill(account, amount_cny=100)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert _daily_rows().count() == 1
    assert _daily_rows().get().amount == Decimal("100")  # 覆盖写不翻倍


@pytest.mark.django_db
def test_window_scope_only_touches_dates_in_range(account):
    _bill(account, amount_cny=100, on=date(2026, 9, 1))
    _bill(account, amount_cny=999, on=date(2026, 8, 1))
    # 预置一条 08-01 的历史聚合，验证不被本期覆盖写误删
    ProjectCostDaily.objects.create(
        stat_date=date(2026, 8, 1),
        project_tag="old",
        tag_status=NORMAL,
        cloud_account=account,
        region="cn-hz",
        resource_type="ecs",
        amount=Decimal("1"),
        bill_count=1,
    )

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert _daily_rows(stat_date=date(2026, 8, 1), project_tag="old").exists()  # 历史保留
    assert _daily_rows(stat_date=date(2026, 9, 1)).count() == 1
    assert not _daily_rows(stat_date=date(2026, 8, 1), amount=Decimal("999")).exists()


@pytest.mark.django_db
def test_negative_refunds_participate(account):
    # A7：退款/调账负行正常进聚合
    _bill(account, amount_cny=100)
    _bill(account, amount_cny=-30)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert _daily_rows().get().amount == Decimal("70")


@pytest.mark.django_db
def test_null_amount_cny_group_skipped(account):
    # 缺汇率（amount_cny 为 NULL）的账单尚未折算：整组无 CNY 金额 → 不生成聚合行，待补录后重算
    _bill(account, rtype="eip", amount_cny=None)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    assert not _daily_rows(resource_type="eip").exists()


@pytest.mark.django_db
def test_null_amount_cny_mixed_group_sums_converted_only(account):
    _bill(account, amount_cny=100)
    _bill(account, amount_cny=None)

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 1))
    row = _daily_rows().get()
    assert row.amount == Decimal("100")  # Sum 忽略 NULL
    assert row.bill_count == 2  # 条数仍计两行


@pytest.mark.django_db
def test_multi_date_window_groups_per_stat_date(account):
    _bill(account, amount_cny=100, on=date(2026, 9, 1))
    _bill(account, amount_cny=50, on=date(2026, 9, 2))

    aggregate_daily(date(2026, 9, 1), date(2026, 9, 2))
    assert _daily_rows().count() == 2
    by_date = {r.stat_date: r.amount for r in _daily_rows()}
    assert by_date == {date(2026, 9, 1): Decimal("100"), date(2026, 9, 2): Decimal("50")}
