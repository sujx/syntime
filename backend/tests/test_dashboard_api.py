"""仪表盘聚合接口测试（api.md 接口9）。

锁定：统一信封 + 一次返回 cards/trend/syncStatus 三块；cards 金额两位小数字符串、
比率/环比未配置为 ``--``、计数与拆分口径；trend 按 resource_type 堆叠（复用接口8
结构，projectTag 承载资源类型码）；syncStatus 各账号最近同步 + 最近聚合完成时间；
三个角色均可访问；未登录 40100。today 由服务端取，故数据相对 localdate 播种以保证确定性。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, SyncLog
from apps.cost.models import ProjectCostDaily
from apps.cost.services import previous_period
from apps.events.models import CloudEvent

DASHBOARD_URL = "/api/dashboard/"


def _role_user(username: str, role: str) -> User:
    Group.objects.get_or_create(name=role)
    user = User.objects.create_user(username, password="pw-12345")
    user.groups.add(Group.objects.get(name=role))
    return user


def _account(name: str, status: str) -> CloudAccount:
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name=name,
        account_type=CloudAccount.AccountType.MAIN,
        ak_cipher="x",
        sk_cipher="y",
        status=status,
    )


def _asset(instance_id: str, status: str) -> CloudAsset:
    return CloudAsset.objects.create(
        resource_type="ecs",
        instance_id=instance_id,
        instance_name=instance_id,
        status=status,
    )


def _cost(stat_date, tag_status, resource_type, amount, account) -> None:  # noqa: ANN001
    ProjectCostDaily.objects.create(
        stat_date=stat_date,
        project_tag="projA" if tag_status == "normal" else "",
        tag_status=tag_status,
        cloud_account=account,
        region="cn-hangzhou",
        resource_type=resource_type,
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
    today = timezone.localdate()
    month_start = today.replace(day=1)
    prev_start, _ = previous_period(month_start, today)

    acc_enabled = _account("acc-enabled", CloudAccount.Status.ENABLED)
    _account("acc-disabled", CloudAccount.Status.DISABLED)

    _asset("i-running", CloudAsset.Status.RUNNING)
    _asset("i-stopped", CloudAsset.Status.STOPPED)

    # 本月：normal ecs 100 + unassigned rds 20 → 合计 120、未分配 20
    _cost(today, "normal", "ecs", "100", acc_enabled)
    _cost(today, "unassigned", "rds", "20", acc_enabled)
    # 上期等长区间：60 → 环比 (120-60)/60*100 = 100
    _cost(prev_start, "normal", "ecs", "60", acc_enabled)

    _event(CloudEvent.Status.UNREAD, CloudEvent.EventLevel.CRITICAL, 1)  # 未读+高危
    _event(CloudEvent.Status.UNREAD, CloudEvent.EventLevel.WARNING, 2)  # 未读+警告
    _event(CloudEvent.Status.READ, CloudEvent.EventLevel.CRITICAL, 3)  # 已读不计
    _event(CloudEvent.Status.HANDLED, CloudEvent.EventLevel.WARNING, 4)  # 排除

    # 账号上的「最近成功同步」与 SyncLog 结束时间刻意不同，用于锁定时间取值来源
    acc_enabled.last_sync_time = datetime(2026, 9, 20, 3, 45, tzinfo=UTC)
    acc_enabled.save(update_fields=["last_sync_time"])
    SyncLog.objects.create(
        cloud_account=acc_enabled,
        sync_type=SyncLog.SyncType.AUTO,
        bill_date_start=month_start,
        bill_date_end=today,
        status=SyncLog.Status.SUCCESS,
        end_time=datetime(2026, 9, 20, 1, 5, tzinfo=UTC),
    )
    AuditLog.objects.create(
        action=AuditLog.Action.AGGREGATE,
        result="success",
        operator="system",
    )
    return today


@pytest.mark.django_db
def test_dashboard_envelope_and_three_blocks(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get(DASHBOARD_URL)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert set(data) == {"cards", "trend", "syncStatus"}


@pytest.mark.django_db
def test_dashboard_cards_values(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    cards = api_client.get(DASHBOARD_URL).json()["data"]["cards"]
    assert cards["cloudAccountTotal"] == 2
    assert cards["enabled"] == 1
    assert cards["disabled"] == 1
    assert cards["assetTotal"] == 2
    assert cards["running"] == 1
    assert cards["stopped"] == 1
    assert cards["monthAmount"] == "120.00"
    assert cards["monthRate"] == "100.00"
    assert cards["isEstimate"] is True
    assert cards["unallocatedAmount"] == "20.00"
    assert cards["unallocatedRatio"] == "16.67"
    assert cards["eventPending"] == 2
    assert cards["eventHigh"] == 1
    assert cards["eventWarning"] == 1


@pytest.mark.django_db
def test_dashboard_trend_grouped_by_resource_type(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    today = seeded
    trend = api_client.get(DASHBOARD_URL).json()["data"]["trend"]
    point = next(p for p in trend["current"] if p["date"] == today.isoformat())
    codes = {item["projectTag"] for item in point["items"]}
    assert codes == {"ecs", "rds"}
    by_code = {item["projectTag"]: item["amount"] for item in point["items"]}
    assert by_code["ecs"] == "100.00"
    assert by_code["rds"] == "20.00"


@pytest.mark.django_db
def test_dashboard_sync_status(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    sync = api_client.get(DASHBOARD_URL).json()["data"]["syncStatus"]
    assert sync["lastAggregateTime"] is not None
    by_name = {a["accountName"]: a for a in sync["accounts"]}
    assert by_name["acc-enabled"]["status"] == SyncLog.Status.SUCCESS
    assert by_name["acc-enabled"]["vendor"] == "aliyun"
    # 时间取 CloudAccount.last_sync_time，非 SyncLog 的 end_time
    assert by_name["acc-enabled"]["lastSyncTime"] == "2026-09-20T03:45:00+00:00"
    assert by_name["acc-disabled"]["status"] is None
    assert by_name["acc-disabled"]["lastSyncTime"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["成本管理员", "云运维", "财务人员"])
def test_dashboard_all_roles_allowed(api_client, role, seeded):
    user = _role_user(f"u-{role}", role)
    api_client.force_authenticate(user=user)
    assert api_client.get(DASHBOARD_URL).json()["code"] == 0


@pytest.mark.django_db
def test_dashboard_unauthenticated(api_client, seeded):
    resp = api_client.get(DASHBOARD_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


@pytest.mark.django_db
def test_dashboard_empty_db_safe(api_client, user_alice, db):
    api_client.force_authenticate(user=user_alice)
    cards = api_client.get(DASHBOARD_URL).json()["data"]["cards"]
    assert cards["cloudAccountTotal"] == 0
    assert cards["monthAmount"] == "0.00"
    assert cards["monthRate"] == "--"
    assert cards["unallocatedRatio"] == "--"
