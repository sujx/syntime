"""平台自算检测 Celery 任务测试（tasks.md 任务 8）。

直接调用任务函数（同步 __call__），FakeRedis 替身验互斥锁与跳过路径的
audit_action=detect。两类检测的口径正确性由 test_event_detection.py 覆盖，
此处只验任务封装：一次扫描跑两类检测、返回计数、互斥占用时跳过且不建事件。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from celery.exceptions import Ignore

import common.tasks as tasks_mod
from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.events.models import CloudEvent
from apps.events.tasks import self_calc_detect


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
def seeded(db):
    """一条 5 天后到期的域名 + 一个超支项目（2026-09）。"""
    CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-1",
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
    )
    account = CloudAccount.objects.get()
    CloudAsset.objects.create(
        resource_type="domain",
        instance_id="a.com",
        instance_name="a.com",
        status=CloudAsset.Status.UNKNOWN,
        expire_time=datetime(2026, 9, 21, 12, 0, tzinfo=UTC) + timedelta(days=5),
    )
    ProjectBudget.objects.create(
        project_tag="projA", bill_month="2026-09", budget_amount=Decimal("100")
    )
    ProjectCostDaily.objects.create(
        stat_date=date(2026, 9, 1),
        project_tag="projA",
        tag_status=ProjectCostDaily.TagStatus.NORMAL,
        cloud_account=account,
        region="cn-hangzhou",
        resource_type="ecs",
        amount=Decimal("150"),
        bill_count=1,
    )


@pytest.mark.django_db
def test_self_calc_detect_runs_both_and_releases_lock(fake_redis, seeded):
    result = self_calc_detect(today_iso="2026-09-21")

    assert result["domain"] == 2  # T-30 / T-7 两档 expiring
    assert result["budget"] == 1  # projA 超支一次
    assert CloudEvent.objects.count() == 3
    assert fake_redis.store == {}  # 锁已释放


@pytest.mark.django_db
def test_self_calc_detect_mutex_busy_skips(fake_redis, seeded):
    fake_redis.store["syntime:mutex:events.self_calc_detect"] = "held-by-other"

    with pytest.raises(Ignore):
        self_calc_detect(today_iso="2026-09-21")

    assert CloudEvent.objects.count() == 0  # body 未执行
    skipped = [a for a in fake_redis._audits if a.get("result") == "skipped"]
    assert skipped and skipped[0]["action"] == "detect"  # audit_action=detect
