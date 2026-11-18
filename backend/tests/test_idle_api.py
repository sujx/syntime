"""闲置资源清单接口（api.md 接口16）：信封与 notice、筛选/排序/分页、权限码、阈值即时生效。

覆盖 F063 的接口部分（四类各自命中且带判定依据、不足 N 天不出现、改 N 即时变化）
与 PRD 3.14-7 的权限口径（财务 40300）。误报提示常驻属前端项，此处只钉后端契约 notice。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone

from apps.assets.idle_rules import IDLE_NOTICE
from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount
from apps.core.models import PlatformSetting

LIST_URL = "/api/assets/idle/"


def _role_user(username: str, role: str | None = None) -> User:
    user = User.objects.create_user(username, password="pw-12345")
    if role:
        Group.objects.get_or_create(name=role)
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def account(db) -> CloudAccount:  # noqa: ANN001
    return CloudAccount.objects.create(
        vendor="aliyun",
        account_name="acc1",
        account_type="main",
        ak_cipher="x",
        sk_cipher="y",
    )


def _make(account: CloudAccount | None, **overrides: object) -> CloudAsset:
    base: dict[str, object] = {
        "cloud_account": account,
        "resource_type": "ecs",
        "instance_id": f"i-{CloudAsset.objects.count() + 1}",
        "status": CloudAsset.Status.STOPPED,
        "charge_type": "postpaid",
        "status_changed_at": timezone.now() - timedelta(days=90),
    }
    base.update(overrides)
    return CloudAsset.objects.create(**base)


@pytest.fixture
def four_criteria(db, account):  # noqa: ANN001
    """四判据各一台 + 一台按量停机 3 天（不该出现）+ 一台运行中（不该出现）。"""
    now = timezone.now()
    _make(account, instance_id="prepaid-1", charge_type="prepaid")
    _make(account, instance_id="postpaid-long")
    _make(account, resource_type="eip", instance_id="eip-1", status=CloudAsset.Status.UNBOUND)
    _make(
        None,
        resource_type="domain",
        instance_id="a.test",
        status=CloudAsset.Status.EXPIRING,
        expire_time=now + timedelta(days=7),
        registrar="示例注册商",
    )
    _make(account, instance_id="postpaid-short", status_changed_at=now - timedelta(days=3))
    _make(account, instance_id="running-1", status=CloudAsset.Status.RUNNING)


@pytest.mark.django_db
def test_envelope_list_and_notice(api_client, four_criteria) -> None:  # noqa: ANN001
    api_client.force_authenticate(user=_role_user("cost1", "成本管理员"))
    body = api_client.get(LIST_URL).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["notice"] == IDLE_NOTICE
    assert {row["instanceId"] for row in data["list"]} == {
        "prepaid-1",
        "postpaid-long",
        "eip-1",
        "a.test",
    }
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["pageSize"] == 20


@pytest.mark.django_db
def test_row_fields_and_verdict_values(api_client, four_criteria) -> None:  # noqa: ANN001
    api_client.force_authenticate(user=_role_user("ops1", "云运维"))
    rows = {r["instanceId"]: r for r in api_client.get(LIST_URL).json()["data"]["list"]}
    assert rows["a.test"]["cloudAccountName"] == "示例注册商"  # 域名取注册商
    assert rows["a.test"]["idleType"] == "domain_expired"
    assert rows["a.test"]["keyMetric"] == {"daysUntilExpiry": 7}
    assert rows["prepaid-1"]["idleType"] == "prepaid_stopped"
    assert rows["prepaid-1"]["idleReason"] == "包年包月资源已停机"
    assert rows["postpaid-long"]["idleType"] == "postpaid_stopped"
    assert rows["postpaid-long"]["keyMetric"]["thresholdDays"] == 14
    assert rows["postpaid-long"]["keyMetric"]["stoppedDays"] == 90
    assert rows["eip-1"]["idleType"] == "eip_unbound"
    assert set(rows["eip-1"]) == {
        "instanceId",
        "instanceName",
        "resourceType",
        "cloudAccountName",
        "region",
        "projectTag",
        "status",
        "idleType",
        "idleReason",
        "keyMetric",
        "expireTime",
    }


@pytest.mark.django_db
def test_threshold_change_takes_effect_immediately(api_client, four_criteria) -> None:
    """F063：改 `idle_stopped_days` 后不重启，下一次查询结果即时变化（90 天行随 120 退出）。"""
    api_client.force_authenticate(user=_role_user("cost2", "成本管理员"))
    row = PlatformSetting.objects.get(setting_key="idle_stopped_days")
    row.setting_value = 120
    row.save(update_fields=["setting_value"])
    ids = {r["instanceId"] for r in api_client.get(LIST_URL).json()["data"]["list"]}
    assert "postpaid-long" not in ids

    row.setting_value = 2
    row.save(update_fields=["setting_value"])
    ids = {r["instanceId"] for r in api_client.get(LIST_URL).json()["data"]["list"]}
    assert "postpaid-long" in ids


@pytest.mark.django_db
def test_filter_sort_and_paging(api_client, four_criteria) -> None:  # noqa: ANN001
    api_client.force_authenticate(user=_role_user("cost3", "成本管理员"))
    data = api_client.get(LIST_URL, {"idleType": ["prepaid_stopped", "eip_unbound"]}).json()["data"]
    assert {r["instanceId"] for r in data["list"]} == {"prepaid-1", "eip-1"}

    data = api_client.get(LIST_URL, {"resourceType": "domain"}).json()["data"]
    assert [r["instanceId"] for r in data["list"]] == ["a.test"]

    data = api_client.get(LIST_URL, {"keyword": "PREPAID"}).json()["data"]  # 大小写不敏感
    assert [r["instanceId"] for r in data["list"]] == ["prepaid-1"]

    data = api_client.get(LIST_URL, {"sortField": "instanceId", "sortOrder": "asc"}).json()["data"]
    assert [r["instanceId"] for r in data["list"]] == [
        "a.test",
        "eip-1",
        "postpaid-long",
        "prepaid-1",
    ]

    data = api_client.get(LIST_URL, {"page": 2, "pageSize": 2}).json()["data"]
    assert data["total"] == 4 and data["pageSize"] == 2 and len(data["list"]) == 2


@pytest.mark.django_db
def test_region_and_account_and_project_filters(api_client, account) -> None:  # noqa: ANN001
    api_client.force_authenticate(user=_role_user("cost4", "成本管理员"))
    _make(account, instance_id="in-hz", region="cn-hangzhou", project_tag="项目A")
    _make(account, instance_id="in-sh", region="cn-shanghai", project_tag="项目B")

    def ids(**params: object) -> list[str]:
        data = api_client.get(LIST_URL, params).json()["data"]
        return [r["instanceId"] for r in data["list"]]

    assert ids(region="cn-hangzhou") == ["in-hz"]
    assert ids(projectTag="项目B") == ["in-sh"]
    assert len(ids(cloudAccountId=account.pk)) == 2
    assert ids(cloudAccountId=999999) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "code"),
    [(None, 40300), ("财务人员", 40300), ("成本管理员", 0), ("云运维", 0)],
)
def test_role_gates(api_client, db, role: str | None, code: int) -> None:  # noqa: ANN001
    user = _role_user(f"u-{role or 'norole'}", role)
    api_client.force_authenticate(user=user)
    assert api_client.get(LIST_URL).json()["code"] == code


@pytest.mark.django_db
def test_unauthenticated_is_40100(api_client, db) -> None:  # noqa: ANN001
    assert api_client.get(LIST_URL).json()["code"] == 40100


@pytest.mark.django_db
def test_invalid_params_are_40001(api_client, db) -> None:  # noqa: ANN001
    api_client.force_authenticate(user=_role_user("cost5", "成本管理员"))
    assert api_client.get(LIST_URL, {"idleType": ["nope"]}).json()["code"] == 40001
    assert api_client.get(LIST_URL, {"sortOrder": "sideways"}).json()["code"] == 40001


@pytest.mark.django_db
def test_d11_fallback_row_survives_the_api_read_path(api_client, account) -> None:  # noqa: ANN001
    """api.md §16「实现口径」的接口级形状：`first_seen_at` 回退行经 `GET` 命中判据 ②。

    与 `test_idle_selectors` 那条同一条防线——若有人把日阈值下推进 SQL
    （`status_changed_at__lte=now - N 天`，spec §8-D12 禁止的形态），这行的 `instanceId`
    会从 `data.list` 里**静默消失**而四门全绿，故断言必须打在真读路径上。
    """
    api_client.force_authenticate(user=_role_user("cost6", "成本管理员"))
    _make(
        account,
        instance_id="fallback-by-first-seen",
        status=CloudAsset.Status.STOPPED,
        status_changed_at=None,
        first_seen_at=timezone.now() - timedelta(days=20),
    )
    rows = {r["instanceId"]: r for r in api_client.get(LIST_URL).json()["data"]["list"]}
    assert rows["fallback-by-first-seen"]["idleType"] == "postpaid_stopped"
    assert rows["fallback-by-first-seen"]["keyMetric"] == {"stoppedDays": 20, "thresholdDays": 14}


# ---------- api.md §16「HTTP 状态映射（实测）」/「已知既有 quirk」四条契约 ----------
# 映射表在 `common/api/response.py` 的 `_DRF_ORDERED` + `exception_handler`，是**别的切片
# 也会改的共享层**：把 `NotFound` 补进表里、或把 `PermissionDenied` 改成真 403，四门都还是绿的，
# 而前端拦截器据此写的分支当场失效。下面每条只钉一对 (status_code, code)。


@pytest.mark.django_db
def test_http_400_for_empty_idle_type(api_client, four_criteria) -> None:  # noqa: ANN001
    """`?idleType=` 传空值 → HTTP 400 + `code=40001`（清空多选须整体省略该参数）。"""
    api_client.force_authenticate(user=_role_user("cost7", "成本管理员"))
    resp = api_client.get(LIST_URL, {"idleType": ""})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


@pytest.mark.django_db
def test_http_404_with_50000_for_out_of_range_page(api_client, four_criteria) -> None:  # noqa: ANN001
    """`?page=99` 越界页 → HTTP 404 + `code=50000`（既有 quirk：DRF `NotFound` 不在映射表里）。"""
    api_client.force_authenticate(user=_role_user("cost8", "成本管理员"))
    resp = api_client.get(LIST_URL, {"page": 99})
    assert resp.status_code == 404
    assert resp.json()["code"] == 50000


@pytest.mark.django_db
def test_http_200_for_forbidden_role_envelope(api_client, four_criteria) -> None:  # noqa: ANN001
    """财务角色 40300 走 **HTTP 200 信封承载**（不是真 403）——拦截器只能按 code 分支。"""
    api_client.force_authenticate(user=_role_user("fin1", "财务人员"))
    resp = api_client.get(LIST_URL)
    assert resp.status_code == 200
    assert resp.json()["code"] == 40300


@pytest.mark.django_db
def test_http_200_and_notice_present_when_nothing_hits(api_client, db) -> None:  # noqa: ANN001
    """已认证但库里没有命中行 → HTTP 200、`total=0`、`list=[]`，**`notice` 仍然在**。

    api.md §16「HTTP 状态映射（实测）」原文是「`code=0` 且无命中 → HTTP 200、`total=0`、
    `list=[]`，**`notice` 仍然在**」；spec US-2 把这条提示写成「任何数据状态下都显示」，
    故空态也不是例外——前端拦截器若在 `total=0` 时丢掉 body 就破坏 PRD 3.14-4。
    """
    api_client.force_authenticate(user=_role_user("ops2", "云运维"))
    resp = api_client.get(LIST_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["list"] == []
    assert data["notice"] == IDLE_NOTICE
