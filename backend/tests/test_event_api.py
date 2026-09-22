"""事件中心接口测试（api.md 接口12 列表 / 接口13 状态更新）。

覆盖：列表 camelCase 出参 + 分页信封 + 默认 occurred_at 倒序、多维过滤、
unreadCount 全局未读数、财务角色 resourceId/instanceName 屏蔽（PRD 4.2）；
状态更新 read/handle/ignore 批量 + handled_by/at + audit_log(action=event_handle)、
财务 40300、云运维放行、未登录 40100、非法 action 40001。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import Group, User

from apps.audit.models import AuditLog
from apps.events.models import CloudEvent, EventTypeDict

LIST_URL = "/api/events/"
STATUS_URL = "/api/events/status/"


def _role_user(username: str, role: str) -> User:
    Group.objects.get_or_create(name=role)
    user = User.objects.create_user(username, password="pw-12345")
    user.groups.add(Group.objects.get(name=role))
    return user


def _event(**overrides) -> CloudEvent:  # noqa: ANN003
    n = overrides.pop("n", 0)
    base = {
        "event_type": "expired",
        "event_level": CloudEvent.EventLevel.CRITICAL,
        "source": CloudEvent.Source.RULE,
        "title": "域名 a.com 已过期",
        "dedup_key": f"expired:{n}",
        "status": CloudEvent.Status.UNREAD,
        "occurred_at": datetime(2026, 9, 10, tzinfo=UTC),
        "resource_type": "domain",
        "resource_id": "a.com",
        "instance_name": "a.com",
    }
    base.update(overrides)
    return CloudEvent.objects.create(**base)


@pytest.fixture
def seeded(db):
    """事件类型字典（可能已随 seed 迁移预置）+ 三条不同时间/状态/类型的事件。"""
    EventTypeDict.objects.get_or_create(
        code="expired",
        defaults={"display_name": "域名过期", "default_level": CloudEvent.EventLevel.CRITICAL},
    )
    EventTypeDict.objects.get_or_create(
        code="budget_overrun",
        defaults={
            "display_name": "预算超支",
            "default_level": CloudEvent.EventLevel.WARNING,
        },
    )
    _event(n=1, occurred_at=datetime(2026, 9, 10, tzinfo=UTC), status=CloudEvent.Status.UNREAD)
    _event(
        n=2,
        event_type="budget_overrun",
        event_level=CloudEvent.EventLevel.WARNING,
        title="项目 projA 预算超支",
        dedup_key="budget_overrun:projA:2026-09",
        occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
        status=CloudEvent.Status.READ,
        resource_id=None,
        instance_name=None,
        project_tag="projA",
    )
    _event(
        n=3,
        title="域名 b.com 即将到期",
        dedup_key="expiring:b.com:7",
        occurred_at=datetime(2026, 9, 14, tzinfo=UTC),
        status=CloudEvent.Status.HANDLED,
        resource_id="b.com",
        instance_name="b.com",
    )


# ---------- 接口12 列表 ----------


@pytest.mark.django_db
def test_list_envelope_and_default_sort_desc(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get(LIST_URL)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["pageSize"] == 20
    # 默认按 occurred_at 倒序：9-14 → 9-12 → 9-10
    titles = [row["title"] for row in data["list"]]
    assert titles == ["域名 b.com 即将到期", "项目 projA 预算超支", "域名 a.com 已过期"]
    first = data["list"][0]
    assert first["eventType"] == "expired"
    assert first["eventTypeName"] == "已过期"
    assert first["eventLevel"] == "critical"
    assert first["source"] == "rule"
    assert first["status"] == "handled"
    assert first["occurredAt"].startswith("2026-09-14")
    assert "receivedAt" in first
    # 出参必须带 id 主键（接口13 eventIds 批量依赖）
    row = data["list"][0]
    event = CloudEvent.objects.get(dedup_key="expiring:b.com:7")
    assert row["id"] == event.pk


@pytest.mark.django_db
def test_list_unread_count_is_global(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    # 即便按 status=handled 过滤，unreadCount 仍是全局未读数（1 条 unread）
    resp = api_client.get(LIST_URL, {"status": "handled"})
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["unreadCount"] == 1


@pytest.mark.django_db
def test_list_filter_by_event_type_multi_and_status(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get(LIST_URL, {"eventType": ["expired"], "status": "unread"})
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["title"] == "域名 a.com 已过期"


@pytest.mark.django_db
def test_list_filter_by_keyword(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get(LIST_URL, {"keyword": "projA"})
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["eventType"] == "budget_overrun"


@pytest.mark.django_db
def test_list_filter_by_date_range(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get(LIST_URL, {"startDate": "2026-09-11", "endDate": "2026-09-13"})
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["list"][0]["title"] == "项目 projA 预算超支"


@pytest.mark.django_db
def test_list_finance_role_masks_resource_fields(api_client, seeded):
    api_client.force_authenticate(user=_role_user("fin1", "财务人员"))
    resp = api_client.get(LIST_URL, {"status": "unread"})
    row = resp.json()["data"]["list"][0]
    # 财务可见事件，但资源标识字段被屏蔽（PRD 4.2）
    assert row["title"] == "域名 a.com 已过期"
    assert row["resourceId"] is None
    assert row["instanceName"] is None


@pytest.mark.django_db
def test_list_unauthenticated_40100(api_client, seeded):
    resp = api_client.get(LIST_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


# ---------- 接口13 状态更新 ----------


@pytest.mark.django_db
def test_status_handle_sets_handler_and_audits(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    evt = CloudEvent.objects.get(dedup_key="expired:1")
    resp = api_client.post(STATUS_URL, {"eventIds": [evt.pk], "action": "handle"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    evt.refresh_from_db()
    assert evt.status == CloudEvent.Status.HANDLED
    assert evt.handled_by == "alice"
    assert evt.handled_at is not None
    audit = AuditLog.objects.filter(action="event_handle")
    assert audit.count() == 1
    entry = audit.first()
    assert entry is not None
    assert entry.operator == "alice"


@pytest.mark.django_db
def test_status_read_does_not_set_handler(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    evt = CloudEvent.objects.get(dedup_key="expired:1")
    resp = api_client.post(STATUS_URL, {"eventIds": [evt.pk], "action": "read"}, format="json")
    assert resp.json()["code"] == 0
    evt.refresh_from_db()
    assert evt.status == CloudEvent.Status.READ
    assert evt.handled_by is None
    assert evt.handled_at is None


@pytest.mark.django_db
def test_status_ignore_batch_updates_all(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    ids = list(CloudEvent.objects.values_list("pk", flat=True))
    resp = api_client.post(STATUS_URL, {"eventIds": ids, "action": "ignore"}, format="json")
    assert resp.json()["data"]["updated"] == 3
    assert CloudEvent.objects.filter(status=CloudEvent.Status.IGNORED).count() == 3


@pytest.mark.django_db
def test_status_ops_role_allowed(api_client, seeded):
    api_client.force_authenticate(user=_role_user("ops1", "云运维"))
    evt = CloudEvent.objects.get(dedup_key="expired:1")
    resp = api_client.post(STATUS_URL, {"eventIds": [evt.pk], "action": "handle"}, format="json")
    assert resp.json()["code"] == 0


@pytest.mark.django_db
def test_status_finance_role_forbidden_40300(api_client, seeded):
    api_client.force_authenticate(user=_role_user("fin1", "财务人员"))
    evt = CloudEvent.objects.get(dedup_key="expired:1")
    resp = api_client.post(STATUS_URL, {"eventIds": [evt.pk], "action": "handle"}, format="json")
    assert resp.json()["code"] == 40300


@pytest.mark.django_db
def test_status_invalid_action_40001(api_client, user_alice, seeded):
    api_client.force_authenticate(user=user_alice)
    evt = CloudEvent.objects.get(dedup_key="expired:1")
    resp = api_client.post(STATUS_URL, {"eventIds": [evt.pk], "action": "bogus"}, format="json")
    assert resp.json()["code"] == 40001
