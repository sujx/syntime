"""平台自算检测测试（tasks.md 任务 8 / PRD 3.12-8）：域名到期 + 预算超支。

自算事件 source=rule，按业务键 dedup 去重，重复扫描不重复产生；
级别取 event_type_dict.default_level（expiring/expired=warning/critical，budget_overrun=warning）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.events.models import CloudEvent
from apps.events.services import detect_budget_overrun, detect_domain_expiry

TODAY = date(2026, 9, 21)


def _aware(day_offset: int) -> datetime:
    """以 TODAY 为基准、偏移 day_offset 天的到期时间（UTC 正午，避免边界跨日）。"""
    return datetime(2026, 9, 21, 12, 0, tzinfo=UTC) + timedelta(days=day_offset)


def _domain(instance_id: str, *, expire_offset: int | None, released: bool = False) -> CloudAsset:
    return CloudAsset.objects.create(
        resource_type="domain",
        instance_id=instance_id,
        instance_name=instance_id,
        status=CloudAsset.Status.UNKNOWN,
        expire_time=None if expire_offset is None else _aware(expire_offset),
        released_at=_aware(0) if released else None,
    )


# ---------- 域名到期检测 ----------


@pytest.mark.django_db
def test_domain_in_notice_window_produces_expiring_per_tier():
    """距到期 5 天：落入 [30,7,1] 的 30/7 两档 → 各产生一次 expiring（警告）。"""
    _domain("a.com", expire_offset=5)
    created = detect_domain_expiry(today=TODAY)
    assert created == 2
    keys = set(CloudEvent.objects.values_list("dedup_key", flat=True))
    assert keys == {"expiring:a.com:30", "expiring:a.com:7"}
    assert all(
        e.event_type == "expiring" and e.event_level == "warning" and e.source == "rule"
        for e in CloudEvent.objects.all()
    )


@pytest.mark.django_db
def test_domain_one_day_out_produces_all_three_tiers():
    _domain("b.com", expire_offset=1)
    created = detect_domain_expiry(today=TODAY)
    assert created == 3
    keys = set(CloudEvent.objects.values_list("dedup_key", flat=True))
    assert keys == {"expiring:b.com:30", "expiring:b.com:7", "expiring:b.com:1"}


@pytest.mark.django_db
def test_expired_domain_produces_expired_critical_only():
    """已过期（days<0）：只产生 expired（严重），不再产生 expiring。"""
    _domain("c.com", expire_offset=-3)
    created = detect_domain_expiry(today=TODAY)
    assert created == 1
    evt = CloudEvent.objects.get()
    assert evt.dedup_key == "expired:c.com"
    assert evt.event_type == "expired"
    assert evt.event_level == "critical"
    assert evt.source == "rule"


@pytest.mark.django_db
def test_far_future_domain_not_flagged():
    _domain("d.com", expire_offset=60)
    assert detect_domain_expiry(today=TODAY) == 0
    assert CloudEvent.objects.count() == 0


@pytest.mark.django_db
def test_domain_without_expire_time_or_released_skipped():
    _domain("e.com", expire_offset=None)
    _domain("f.com", expire_offset=5, released=True)
    assert detect_domain_expiry(today=TODAY) == 0
    assert CloudEvent.objects.count() == 0


@pytest.mark.django_db
def test_non_domain_asset_not_flagged():
    CloudAsset.objects.create(
        resource_type="ecs",
        instance_id="i-1",
        status=CloudAsset.Status.RUNNING,
        expire_time=_aware(5),
    )
    assert detect_domain_expiry(today=TODAY) == 0


@pytest.mark.django_db
def test_repeat_scan_is_idempotent():
    _domain("g.com", expire_offset=5)
    assert detect_domain_expiry(today=TODAY) == 2
    assert detect_domain_expiry(today=TODAY) == 0  # 第二次扫描不重复建事件
    assert CloudEvent.objects.count() == 2


# ---------- 预算超支检测 ----------


@pytest.fixture
def account(db):
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc-1",
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
    )


def _daily(
    account,
    *,
    tag: str,
    amount: str,
    day: int,
    status: str = ProjectCostDaily.TagStatus.NORMAL,
) -> None:
    ProjectCostDaily.objects.create(
        stat_date=date(2026, 9, day),
        project_tag=tag,
        tag_status=status,
        cloud_account=account,
        region="cn-hangzhou",
        resource_type="ecs",
        amount=Decimal(amount),
        bill_count=1,
    )


def _budget(tag: str, amount: str, month: str = "2026-09") -> None:
    ProjectBudget.objects.create(project_tag=tag, bill_month=month, budget_amount=Decimal(amount))


@pytest.mark.django_db
def test_over_budget_produces_event(account):
    _budget("projA", "100")
    _daily(account, tag="projA", amount="150", day=1)
    created = detect_budget_overrun(bill_month="2026-09")
    assert created == 1
    evt = CloudEvent.objects.get()
    assert evt.dedup_key == "budget_overrun:projA:2026-09"
    assert evt.event_type == "budget_overrun"
    assert evt.event_level == "warning"
    assert evt.source == "rule"
    assert evt.project_tag == "projA"
    metric = evt.metric_json
    assert metric is not None
    assert metric["billMonth"] == "2026-09"
    assert Decimal(metric["amount"]) == Decimal("150")
    assert Decimal(metric["budget"]) == Decimal("100")
    assert Decimal(metric["ratio"]) == Decimal("150")


@pytest.mark.django_db
def test_under_budget_no_event(account):
    _budget("projA", "200")
    _daily(account, tag="projA", amount="150", day=1)
    assert detect_budget_overrun(bill_month="2026-09") == 0
    assert CloudEvent.objects.count() == 0


@pytest.mark.django_db
def test_exactly_100pct_not_over(account):
    _budget("projA", "150")
    _daily(account, tag="projA", amount="150", day=1)
    assert detect_budget_overrun(bill_month="2026-09") == 0  # >100 才算超支


@pytest.mark.django_db
def test_no_budget_configured_no_event(account):
    _daily(account, tag="projA", amount="999", day=1)
    assert detect_budget_overrun(bill_month="2026-09") == 0


@pytest.mark.django_db
def test_only_normal_rows_counted(account):
    """未分配/冲突行不计入项目支出（PRD 2.2.2：仅 NORMAL 行参与预算占比）。"""
    _budget("projA", "100")
    _daily(account, tag="projA", amount="150", day=1)  # 计入
    _daily(
        account,
        tag="projA",
        amount="500",
        day=2,
        status=ProjectCostDaily.TagStatus.CONFLICT,
    )  # 不计入
    detect_budget_overrun(bill_month="2026-09")
    evt = CloudEvent.objects.get()
    metric = evt.metric_json
    assert metric is not None
    assert Decimal(metric["amount"]) == Decimal("150")


@pytest.mark.django_db
def test_budget_other_month_not_scanned(account):
    _budget("projA", "100", month="2026-08")
    _daily(account, tag="projA", amount="150", day=1)  # 9 月支出，8 月预算
    assert detect_budget_overrun(bill_month="2026-09") == 0


@pytest.mark.django_db
def test_budget_default_month_from_today(account):
    _budget("projA", "100", month="2026-09")
    _daily(account, tag="projA", amount="150", day=1)
    assert detect_budget_overrun(today=TODAY) == 1  # 不传 bill_month → 取 today 的 YYYY-MM


@pytest.mark.django_db
def test_budget_repeat_scan_idempotent(account):
    _budget("projA", "100")
    _daily(account, tag="projA", amount="150", day=1)
    assert detect_budget_overrun(bill_month="2026-09") == 1
    assert detect_budget_overrun(bill_month="2026-09") == 0
    assert CloudEvent.objects.count() == 1
