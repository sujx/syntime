"""§6 账单链路幂等单测：同步窗口（uk_sync_window）+ 账单 upsert / 重算覆盖写（uk_bill）。

依赖 DB（含分区表 cloud_bill_detail 真实 DDL）；汇率种子按用例自建。
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.billing.models import CloudAccount, CloudBillDetail, ExchangeRate, SyncLog
from apps.billing.services import (
    build_bill_row,
    claim_sync_window,
    recalc_bill_window,
    release_sync_window,
    upsert_bill_lines,
)
from common.exceptions import SyncWindowConflictError
from providers.base import BillLine

D1, D2 = date(2026, 9, 1), date(2026, 9, 2)


@pytest.fixture
def account() -> CloudAccount:
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc1",
        account_type="main",
        ak_cipher="x",
        sk_cipher="y",
    )


def _line(*, bill_date: date = D1, instance_id: str = "i-1", amount: str = "1.23") -> BillLine:
    return BillLine(
        bill_date=bill_date,
        resource_type="ecs",
        charge_type="postpaid",
        currency="USD",
        amount=Decimal(amount),
        instance_id=instance_id,
        region="cn-hangzhou",
        raw_tags='{"project":"p1"}',
    )


# ---------- 同步窗口（uk_sync_window / E010 / F026） ----------


@pytest.mark.django_db
def test_claim_new_window_creates_running(account):
    row = claim_sync_window(account, SyncLog.SyncType.AUTO, D1, D2)
    assert row.status == SyncLog.Status.RUNNING
    assert row.insert_count == 0


@pytest.mark.django_db
def test_claim_running_window_rejected_with_40900(account):
    claim_sync_window(account, SyncLog.SyncType.MANUAL, D1, D2)
    with pytest.raises(SyncWindowConflictError) as exc_info:
        claim_sync_window(account, SyncLog.SyncType.MANUAL, D1, D2)
    assert exc_info.value.code == 40900
    # 同窗口另一触发方式不冲突（uk 含 sync_type）
    other = claim_sync_window(account, SyncLog.SyncType.AUTO, D1, D2)
    assert other.pk != SyncLog.objects.filter(sync_type="manual").get().pk


@pytest.mark.django_db
def test_claim_after_success_reuses_row_and_resets(account):
    first = claim_sync_window(account, SyncLog.SyncType.MANUAL, D1, D2)
    release_sync_window(first, SyncLog.Status.SUCCESS, insert_count=5, update_count=2)
    again = claim_sync_window(account, SyncLog.SyncType.MANUAL, D1, D2)
    assert again.pk == first.pk  # uk_sync_window 强制复用同一行
    assert again.status == SyncLog.Status.RUNNING
    assert again.insert_count == 0
    assert again.update_count == 0
    assert again.error_msg is None
    assert SyncLog.objects.count() == 1


@pytest.mark.django_db
def test_claim_after_failure_clears_error(account):
    first = claim_sync_window(account, SyncLog.SyncType.AUTO, D1, D2)
    release_sync_window(first, SyncLog.Status.FAILED, error_msg="throttled: retry exhausted")
    again = claim_sync_window(account, SyncLog.SyncType.AUTO, D1, D2)
    assert again.status == SyncLog.Status.RUNNING
    assert again.error_msg is None


@pytest.mark.django_db
def test_release_writes_final_state(account):
    row = claim_sync_window(account, SyncLog.SyncType.AUTO, D1, D2)
    release_sync_window(row, SyncLog.Status.SUCCESS, insert_count=3, update_count=4)
    row.refresh_from_db()
    assert row.status == SyncLog.Status.SUCCESS
    assert (row.insert_count, row.update_count) == (3, 4)
    assert row.end_time is not None


# ---------- 折算与标签归属（build_bill_row） ----------


@pytest.mark.django_db
def test_build_bill_row_cny_uses_rate_one(account):
    cny_line = BillLine(
        bill_date=D1,
        resource_type="ecs",
        charge_type="postpaid",
        currency="CNY",
        amount=Decimal("2.50"),
        instance_id="i-1",
    )
    row = build_bill_row(account, cny_line, tag_values=["p1"])
    assert row.exchange_rate == Decimal(1)
    assert row.amount_cny == Decimal("2.50")


@pytest.mark.django_db
def test_build_bill_row_usd_converts_by_rate(account):
    ExchangeRate.objects.create(currency="USD", rate_date=D1, rate_to_cny=Decimal("7.10000000"))
    row = build_bill_row(account, _line(amount="1.23"), tag_values=["p1"])
    assert row.exchange_rate == Decimal("7.10000000")
    assert row.amount_cny == Decimal("8.73300000")
    assert row.bill_month == "2026-09"


@pytest.mark.django_db
def test_build_bill_row_missing_rate_not_blocked(account):
    row = build_bill_row(account, _line(), tag_values=["p1"])
    # 缺失汇率不阻断入库：折算列落 NULL，待补录回溯重算（database.md 表 9）
    assert row.exchange_rate is None
    assert row.amount_cny is None


@pytest.mark.django_db
def test_build_bill_row_tag_ownership(account):
    assert build_bill_row(account, _line(), tag_values=["p1"]).tag_status == "normal"
    assert build_bill_row(account, _line(), tag_values=[]).tag_status == "unassigned"
    conflict = build_bill_row(account, _line(), tag_values=["p1", "p2"])
    assert conflict.tag_status == "conflict"
    assert conflict.project_tag == "p1"  # 冲突时取首个值供治理定位


# ---------- 账单 upsert（uk_bill / F026） ----------


@pytest.mark.django_db
def test_upsert_repeat_never_doubles(account):
    def _rows() -> list:
        return [
            build_bill_row(account, _line(instance_id=f"i-{n}"), tag_values=["p1"]) for n in (1, 2)
        ]

    assert upsert_bill_lines(_rows()) == (2, 0)
    assert upsert_bill_lines(_rows()) == (0, 2)  # 全量覆盖，无新增
    assert CloudBillDetail.objects.count() == 2


@pytest.mark.django_db
def test_upsert_updates_amount_to_latest(account):
    upsert_bill_lines([build_bill_row(account, _line(), tag_values=["p1"])])
    upsert_bill_lines([build_bill_row(account, _line(amount="9.99"), tag_values=["p1"])])
    row = CloudBillDetail.objects.get()
    assert row.amount == Decimal("9.99")  # 最新口径覆盖，不累加


@pytest.mark.django_db
def test_upsert_dedupes_within_batch(account):
    rows = [
        build_bill_row(account, _line(), tag_values=["p1"]),
        build_bill_row(account, _line(amount="5.00"), tag_values=["p1"]),
    ]
    inserted, updated = upsert_bill_lines(rows)  # 同键取后者
    assert (inserted, updated) == (1, 0)
    assert CloudBillDetail.objects.get().amount == Decimal("5.00")


@pytest.mark.django_db
def test_upsert_empty_is_noop(account):
    assert upsert_bill_lines([]) == (0, 0)


# ---------- 重算窗口（DELETE + INSERT 覆盖写） ----------


@pytest.mark.django_db
def test_recalc_window_replaces_only_within_window(account):
    upsert_bill_lines(
        [
            build_bill_row(account, _line(bill_date=D1, instance_id="i-1"), tag_values=["p1"]),
            build_bill_row(account, _line(bill_date=D2, instance_id="i-2"), tag_values=["p1"]),
        ]
    )
    replacement = [
        build_bill_row(account, _line(bill_date=D1, instance_id="i-9"), tag_values=["p1"])
    ]
    deleted, inserted = recalc_bill_window(account, D1, D1, replacement)
    assert (deleted, inserted) == (1, 1)
    # 窗口内旧行（i-1）被替换，窗口外（i-2）不受影响
    assert set(CloudBillDetail.objects.values_list("instance_id", flat=True)) == {"i-9", "i-2"}


@pytest.mark.django_db
def test_recalc_window_repeat_is_idempotent(account):
    def _rows() -> list:
        return [build_bill_row(account, _line(instance_id="i-1"), tag_values=["p1"])]

    recalc_bill_window(account, D1, D1, _rows())
    deleted, inserted = recalc_bill_window(account, D1, D1, _rows())
    assert (deleted, inserted) == (1, 1)
    assert CloudBillDetail.objects.count() == 1
