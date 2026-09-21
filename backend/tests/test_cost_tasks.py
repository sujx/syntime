"""成本预聚合 Celery 任务测试（tasks.md 任务2）。

直接调用任务函数（同步执行 __call__），用 FakeRedis 替身验证互斥锁获取/释放与
互斥占用时跳过；audit_action=aggregate 经跳过路径的 record_audit 断言。
聚合落库正确性由 test_cost_aggregate.py 覆盖，此处只验任务封装与调度窗口计算。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from celery.exceptions import Ignore

import common.tasks as tasks_mod
from apps.billing.models import CloudAccount, CloudBillDetail
from apps.cost.models import ProjectCostDaily
from apps.cost.tasks import aggregate_cost_daily, previous_month_range, reaggregate_previous_month


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):  # noqa: ANN001, ANN201
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, *keys_and_args):  # noqa: ANN001, ANN201
        key, token = keys_and_args[0], keys_and_args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(tasks_mod, "get_lock_client", lambda: fake)
    audits: list[dict] = []
    monkeypatch.setattr(
        tasks_mod, "record_audit", lambda action, **kw: audits.append({"action": action, **kw})
    )
    fake._audits = audits  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def account(db):
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-1",
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
    )


def _bill(account, *, amount_cny=100, on=date(2026, 9, 1), rtype="ecs"):
    return CloudBillDetail.objects.create(
        cloud_account=account,
        region="cn-hz",
        instance_id=f"i-{on.day}-{rtype}",
        resource_type=rtype,
        project_tag="projA",
        tag_status=ProjectCostDaily.TagStatus.NORMAL,
        charge_type="PostPaid",
        currency="CNY",
        amount=Decimal(str(amount_cny)),
        amount_cny=Decimal(str(amount_cny)),
        bill_date=on,
        bill_month=f"{on.year:04d}-{on.month:02d}",
    )


# ---------------------------------------------------------------- previous_month_range


def test_previous_month_range_mid_month():
    assert previous_month_range(date(2026, 9, 21)) == (date(2026, 8, 1), date(2026, 8, 31))


def test_previous_month_range_january_rolls_to_prev_year():
    assert previous_month_range(date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


def test_previous_month_range_leap_february():
    assert previous_month_range(date(2024, 3, 10)) == (date(2024, 2, 1), date(2024, 2, 29))


# ---------------------------------------------------------------- 任务封装


@pytest.mark.django_db
def test_aggregate_task_writes_and_releases_lock(fake_redis, account):
    _bill(account, amount_cny=100)

    result = aggregate_cost_daily("2026-09-01", "2026-09-01")

    assert result["inserted"] == 1
    assert ProjectCostDaily.objects.count() == 1
    assert fake_redis.store == {}  # 锁已释放


@pytest.mark.django_db
def test_aggregate_task_mutex_busy_skips(fake_redis, account):
    _bill(account, amount_cny=100)
    fake_redis.store["syntime:mutex:cost.aggregate_daily"] = "held-by-other"

    with pytest.raises(Ignore):
        aggregate_cost_daily("2026-09-01", "2026-09-01")

    assert ProjectCostDaily.objects.count() == 0  # body 未执行
    skipped = [a for a in fake_redis._audits if a.get("result") == "skipped"]
    assert skipped and skipped[0]["action"] == "aggregate"  # audit_action=aggregate


@pytest.mark.django_db
def test_reaggregate_previous_month_uses_prev_window(fake_redis, account):
    # 账单落在上一账期（2026-08），以 2026-09-03 触发月度全量重算
    _bill(account, amount_cny=250, on=date(2026, 8, 15))

    result = reaggregate_previous_month(today_iso="2026-09-03")

    assert result["start"] == "2026-08-01" and result["end"] == "2026-08-31"
    assert ProjectCostDaily.objects.get().amount == Decimal("250")
