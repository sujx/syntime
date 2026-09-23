"""仪表盘 selector 口径测试（api.md 接口9 cards + 接口6 syncStatus）。

注入 today=2026-09-21 保证确定性。口径全部复用既有定义（cost.services 的
previous_period/mom_change_pct、未分配=unassigned+conflict、事件级别），
本测试锁定：账号/资产计数（资产排除 released_at 软删）、本月金额与等长环比、
未分配金额与占比、待处理事件（仅未读）高危/警告拆分、同步状态取各账号
``last_sync_time``（最近成功同步）+ 最近一条 sync_log 状态、最近聚合完成时间取
最近一条 aggregate 成功审计。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.assets.models import CloudAsset
from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, SyncLog
from apps.core.selectors import dashboard_cards, sync_status
from apps.cost.models import ProjectCostDaily
from apps.events.models import CloudEvent

TODAY = date(2026, 9, 21)


def _account(name: str, status: str) -> CloudAccount:
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name=name,
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
        status=status,
    )


def _asset(instance_id: str, status: str, *, released: bool = False) -> CloudAsset:
    return CloudAsset.objects.create(
        resource_type="ecs",
        instance_id=instance_id,
        instance_name=instance_id,
        status=status,
        released_at=datetime(2026, 9, 1, tzinfo=UTC) if released else None,
    )


def _cost(stat_date: date, tag_status: str, amount: str, account: CloudAccount) -> None:
    ProjectCostDaily.objects.create(
        stat_date=stat_date,
        project_tag="projA" if tag_status == "normal" else "",
        tag_status=tag_status,
        cloud_account=account,
        region="cn-hangzhou",
        resource_type="ecs",
        amount=Decimal(amount),
        bill_count=1,
    )


def _event(status: str, level: str, n: int) -> None:
    CloudEvent.objects.create(
        event_type="expired",
        event_level=level,
        source=CloudEvent.Source.RULE,
        title=f"evt-{n}",
        dedup_key=f"k:{n}",
        status=status,
    )


@pytest.fixture
def seeded(db):
    acc1 = _account("acc-enabled", CloudAccount.Status.ENABLED)
    _account("acc-disabled", CloudAccount.Status.DISABLED)

    _asset("i-run1", CloudAsset.Status.RUNNING)
    _asset("i-run2", CloudAsset.Status.RUNNING)
    _asset("i-stop1", CloudAsset.Status.STOPPED)
    _asset("i-gone", CloudAsset.Status.RUNNING, released=True)  # 软删，应排除

    # 本月 [2026-09-01, 2026-09-21]：normal 100 + unassigned 20 → 合计 120、未分配 20
    _cost(date(2026, 9, 10), ProjectCostDaily.TagStatus.NORMAL, "100", acc1)
    _cost(date(2026, 9, 11), ProjectCostDaily.TagStatus.UNASSIGNED, "20", acc1)
    # 上期等长前移 [2026-08-11, 2026-08-31]：60
    _cost(date(2026, 8, 15), ProjectCostDaily.TagStatus.NORMAL, "60", acc1)

    _event(CloudEvent.Status.UNREAD, CloudEvent.EventLevel.CRITICAL, 1)  # 未读+高危
    _event(CloudEvent.Status.UNREAD, CloudEvent.EventLevel.WARNING, 2)  # 未读+警告
    _event(
        CloudEvent.Status.READ, CloudEvent.EventLevel.CRITICAL, 3
    )  # 已读不计（eventPending=未读）
    _event(CloudEvent.Status.HANDLED, CloudEvent.EventLevel.WARNING, 4)  # 排除
    _event(CloudEvent.Status.IGNORED, CloudEvent.EventLevel.CRITICAL, 5)  # 排除

    # 账号上的「最近成功同步」与 SyncLog 的结束时间刻意不同，用于区分时间取值来源
    acc1.last_sync_time = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    acc1.save(update_fields=["last_sync_time"])
    SyncLog.objects.create(
        cloud_account=acc1,
        sync_type=SyncLog.SyncType.AUTO,
        bill_date_start=date(2026, 9, 1),
        bill_date_end=date(2026, 9, 20),
        status=SyncLog.Status.SUCCESS,
        end_time=datetime(2026, 9, 20, 2, 30, tzinfo=UTC),
    )
    AuditLog.objects.create(action=AuditLog.Action.AGGREGATE, result="success")
    return acc1


@pytest.mark.django_db
def test_dashboard_cards_counts(seeded):
    cards = dashboard_cards(today=TODAY)
    assert cards.cloud_account_total == 2
    assert cards.enabled == 1
    assert cards.disabled == 1
    # 资产排除软删的 i-gone
    assert cards.asset_total == 3
    assert cards.running == 2
    assert cards.stopped == 1


@pytest.mark.django_db
def test_dashboard_cards_month_amount_and_rate(seeded):
    cards = dashboard_cards(today=TODAY)
    assert cards.month_amount == Decimal("120")
    # 环比 = (120 - 60) / 60 * 100 = 100
    assert cards.month_rate == Decimal("100")
    assert cards.is_estimate is True  # 当月未出账，含预估


@pytest.mark.django_db
def test_dashboard_cards_unallocated(seeded):
    cards = dashboard_cards(today=TODAY)
    assert cards.unallocated_amount == Decimal("20")
    assert cards.unallocated_ratio == Decimal("20") / Decimal("120") * Decimal("100")


@pytest.mark.django_db
def test_dashboard_cards_events(seeded):
    cards = dashboard_cards(today=TODAY)
    assert cards.event_pending == 2  # 仅未读（PRD 3.12-1：未读数同步到「待处理事件」卡片）
    assert cards.event_high == 1  # 未读中的 critical
    assert cards.event_warning == 1  # 未读中的 warning


@pytest.mark.django_db
def test_dashboard_cards_no_data_is_safe(db):
    """空库不崩：金额 0、环比 None（--）、占比 None、计数全 0。"""
    cards = dashboard_cards(today=TODAY)
    assert cards.cloud_account_total == 0
    assert cards.month_amount == Decimal("0")
    assert cards.month_rate is None
    assert cards.unallocated_ratio is None
    assert cards.event_pending == 0


@pytest.mark.django_db
def test_sync_status_per_account_and_aggregate_time(seeded):
    status = sync_status()
    by_name = {a.account_name: a for a in status.accounts}
    assert by_name["acc-enabled"].status == SyncLog.Status.SUCCESS
    # 时间取 CloudAccount.last_sync_time（最近成功同步），非 SyncLog 的 end_time
    assert by_name["acc-enabled"].last_sync_time == datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    # 无同步日志的账号：状态为空、无最近成功同步时间，仍出现在列表中
    assert by_name["acc-disabled"].status is None
    assert by_name["acc-disabled"].last_sync_time is None
    assert status.last_aggregate_time is not None


@pytest.mark.django_db
def test_sync_status_time_survives_without_sync_log(db):
    """有「最近成功同步」但无 sync_log 行时仍需给出时间（状态仍为空）。"""
    stamp = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    acc = _account("acc-no-log", CloudAccount.Status.ENABLED)
    acc.last_sync_time = stamp
    acc.save(update_fields=["last_sync_time"])

    row = next(a for a in sync_status().accounts if a.account_name == "acc-no-log")
    assert row.last_sync_time == stamp
    assert row.status is None
