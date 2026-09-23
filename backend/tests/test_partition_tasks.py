"""分区维护 Celery 任务测试（tasks.md 任务 6 / PRD 4.4-5，platform.md 9.1 beat）。

直接调用任务函数（同步 __call__），FakeRedis 替身验互斥锁与跳过路径的
audit_action=maintain。分区 DDL 与审计清理的口径正确性分别由
test_partition_maintenance.py / test_audit_purge.py 覆盖，此处只验任务编排：
一次跑「预建 + 归档 DETACH + 审计清理」三件事、返回计数、互斥占用时跳过。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from celery.exceptions import Ignore

import common.tasks as tasks_mod
from apps.audit.models import AuditLog
from apps.billing.partitions import ensure_monthly_partition
from apps.billing.tasks import partition_maintenance


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


def _log(created: datetime) -> AuditLog:
    row = AuditLog.objects.create(action=AuditLog.Action.QUERY, operator="t")
    AuditLog.objects.filter(pk=row.pk).update(create_time=created)
    return row


@pytest.fixture
def seeded(db):
    """一个远古账单分区（2020-01，应被 DETACH）+ 一旧一新两条审计日志。"""
    ensure_monthly_partition(2020, 1)
    _log(datetime(2025, 1, 1, tzinfo=UTC))  # 早于 12 个月保留线，应清理
    _log(datetime(2026, 9, 1, tzinfo=UTC))  # 近期，应保留


@pytest.mark.django_db
def test_partition_maintenance_orchestrates_three(fake_redis, seeded):
    result = partition_maintenance(today_iso="2026-09-21")

    # 预建当月 + 未来 2 个月
    assert "cloud_bill_detail_2026_09" in result["ensured"]
    assert "cloud_bill_detail_2026_10" in result["ensured"]
    assert "cloud_bill_detail_2026_11" in result["ensured"]
    # 归档：2020-01 早于 24 个月保留线被 DETACH
    assert result["detached"] == ["cloud_bill_detail_2020_01"]
    # 审计清理：仅删早于保留线的一条
    assert result["audit_purged"] == 1
    assert AuditLog.objects.count() == 1
    assert fake_redis.store == {}  # 锁已释放


@pytest.mark.django_db
def test_partition_maintenance_mutex_busy_skips(fake_redis, seeded):
    fake_redis.store["syntime:mutex:billing.partition_maintenance"] = "held-by-other"

    with pytest.raises(Ignore):
        partition_maintenance(today_iso="2026-09-21")

    skipped = [a for a in fake_redis._audits if a.get("result") == "skipped"]
    assert skipped and skipped[0]["action"] == "maintain"  # audit_action=maintain
