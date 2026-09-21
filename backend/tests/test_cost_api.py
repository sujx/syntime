"""成本查询接口集成测试（接口1 汇总 / 接口2 明细 / 接口8 趋势）。

走真实 config.urls（tests.urls_api_base 已并入），验证统一信封、camelCase 字段、
环比/预算「--」降级、财务字段级屏蔽（R006）、分页上限与趋势含预估标记。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User

from apps.billing.models import CloudAccount, CloudBillDetail, ResourceTypeDict
from apps.cost.models import ProjectBudget, ProjectCostDaily

SUMMARY_URL = "/api/cost/summary/"
DETAIL_URL = "/api/cost/details/"
TREND_URL = "/api/cost/trend/"


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
def resource_types(db):
    ResourceTypeDict.objects.all().delete()
    ResourceTypeDict.objects.create(code="ecs", display_name="云服务器", sort_order=1, enabled=True)
    ResourceTypeDict.objects.create(code="rds", display_name="数据库", sort_order=2, enabled=True)
    return ["ecs", "rds"]


def _role_user(name: str, group: str) -> User:
    Group.objects.get_or_create(name=group)
    user = User.objects.create_user(name, password="pw-12345")
    user.groups.add(Group.objects.get(name=group))
    return user


@pytest.fixture
def admin_client(api_client, db):
    api_client.force_authenticate(_role_user("admin1", "成本管理员"))
    return api_client


@pytest.fixture
def finance_client(api_client, db):
    api_client.force_authenticate(_role_user("fin1", "财务人员"))
    return api_client


def _daily(account, *, tag, status, rtype, amount, on=date(2026, 9, 1), region="cn-hz"):
    return ProjectCostDaily.objects.create(
        stat_date=on,
        project_tag=tag,
        tag_status=status,
        cloud_account=account,
        region=region,
        resource_type=rtype,
        amount=Decimal(str(amount)),
        bill_count=1,
    )


def _bill(
    account,
    *,
    instance,
    rtype="ecs",
    tag="projA",
    status="normal",
    amount_cny=100,
    region="cn-hz",
    charge="PostPaid",
    on=date(2026, 9, 1),
):
    return CloudBillDetail.objects.create(
        cloud_account=account,
        region=region,
        instance_id=instance,
        resource_type=rtype,
        project_tag=tag,
        tag_status=status,
        charge_type=charge,
        currency="CNY",
        amount=Decimal(str(amount_cny)),
        amount_cny=Decimal(str(amount_cny)),
        bill_date=on,
        bill_month=f"{on.year:04d}-{on.month:02d}",
    )


# ---------------------------------------------------------------- 鉴权


@pytest.mark.django_db
def test_summary_requires_auth(api_client):
    resp = api_client.get(SUMMARY_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


# ---------------------------------------------------------------- 接口1 汇总


@pytest.mark.django_db
def test_summary_envelope_and_shape(admin_client, account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)
    _daily(account, tag="projA", status="normal", rtype="rds", amount=50)

    resp = admin_client.get(SUMMARY_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["message"] == "ok"
    data = body["data"]

    assert [rt["code"] for rt in data["resourceTypes"]] == ["ecs", "rds"]
    assert data["summary"]["totalAmount"] == "150.00"
    assert data["summary"]["amountByResourceType"] == {"ecs": "100.00", "rds": "50.00"}
    assert data["total"] == 1 and data["page"] == 1

    row = data["list"][0]
    assert row["projectTag"] == "projA"
    assert row["tagStatus"] == "normal"
    assert row["totalAmount"] == "150.00"
    assert row["amountByResourceType"] == {"ecs": "100.00", "rds": "50.00"}
    assert row["statRange"] == {"start": "2026-09-01", "end": "2026-09-10"}
    assert row["lastPeriodRange"] == {"start": "2026-08-22", "end": "2026-08-31"}


@pytest.mark.django_db
def test_summary_rate_and_budget_dash_when_unavailable(admin_client, account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100)  # 无上期、无预算

    row = admin_client.get(
        SUMMARY_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10"}
    ).json()["data"]["list"][0]
    assert row["rate"] == "--"  # 上期为 0 → 环比 --
    assert row["budgetAmount"] == "--"  # 未配置预算 → --
    assert row["budgetRate"] == "--"
    assert row["overBudget"] is False


@pytest.mark.django_db
def test_summary_budget_rate_and_over_budget(admin_client, account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=150)
    ProjectBudget.objects.create(
        project_tag="projA", bill_month="2026-09", budget_amount=Decimal("100")
    )

    row = admin_client.get(
        SUMMARY_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10"}
    ).json()["data"]["list"][0]
    assert row["budgetAmount"] == "100.00"
    assert row["budgetRate"] == "150.00"
    assert row["overBudget"] is True


@pytest.mark.django_db
def test_summary_unallocated_merged_row(admin_client, account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=70)
    _daily(account, tag="projC", status="conflict", rtype="ecs", amount=30)

    data = admin_client.get(
        SUMMARY_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10"}
    ).json()["data"]
    assert data["total"] == 1
    row = data["list"][0]
    assert row["projectTag"] == "未分配成本"
    assert row["tagStatus"] is None
    assert row["totalAmount"] == "100.00"


@pytest.mark.django_db
def test_summary_validates_bad_params(admin_client, account, resource_types):
    # end 早于 start → 参数校验 40001（DRF ValidationError → HTTP 400）
    resp = admin_client.get(SUMMARY_URL, {"startDate": "2026-09-10", "endDate": "2026-09-01"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


# ---------------------------------------------------------------- 接口2 明细


@pytest.mark.django_db
def test_detail_shape_for_cost_admin(admin_client, account, resource_types):
    _bill(account, instance="i-1", rtype="ecs", amount_cny=100)

    resp = admin_client.get(
        DETAIL_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10", "projectTag": "projA"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    row = data["list"][0]
    assert row["instanceId"] == "i-1"  # 成本管理员可见
    assert row["resourceType"] == "ecs"
    assert row["cloudAccountName"] == "acc-1"
    assert row["region"] == "cn-hz"
    assert row["amount"] == "100.00"
    assert row["chargeType"] == "PostPaid"
    assert row["tagStatus"] == "normal"


@pytest.mark.django_db
def test_detail_finance_instance_id_masked(finance_client, account, resource_types):
    # R006：财务角色 instanceId 返回 null，其余字段正常
    _bill(account, instance="i-1", rtype="ecs", amount_cny=100)

    row = finance_client.get(
        DETAIL_URL, {"startDate": "2026-09-01", "endDate": "2026-09-10", "projectTag": "projA"}
    ).json()["data"]["list"][0]
    assert row["instanceId"] is None
    assert row["resourceType"] == "ecs"
    assert row["amount"] == "100.00"


@pytest.mark.django_db
def test_detail_page_size_capped_at_100(admin_client, account, resource_types):
    _bill(account, instance="i-1")

    resp = admin_client.get(
        DETAIL_URL,
        {"startDate": "2026-09-01", "endDate": "2026-09-10", "pageSize": "500"},
    )
    assert resp.json()["data"]["pageSize"] == 100


# ---------------------------------------------------------------- 接口8 趋势


@pytest.mark.django_db
def test_trend_shape(admin_client, account, resource_types):
    _daily(account, tag="projA", status="normal", rtype="ecs", amount=100, on=date(2026, 9, 1))

    resp = admin_client.get(TREND_URL, {"startDate": "2026-09-01", "endDate": "2026-09-02"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["statRange"] == {"start": "2026-09-01", "end": "2026-09-02"}
    assert data["compareRange"] == {"start": "2026-08-30", "end": "2026-08-31"}
    assert [p["date"] for p in data["current"]] == ["2026-09-01", "2026-09-02"]
    day1 = data["current"][0]
    assert day1["items"] == [{"projectTag": "projA", "tagStatus": "normal", "amount": "100.00"}]
    assert data["current"][1]["items"] == []


@pytest.mark.django_db
def test_trend_merges_unallocated(admin_client, account, resource_types):
    _daily(account, tag="", status="unassigned", rtype="ecs", amount=70, on=date(2026, 9, 1))
    _daily(account, tag="projC", status="conflict", rtype="ecs", amount=30, on=date(2026, 9, 1))

    items = admin_client.get(
        TREND_URL, {"startDate": "2026-09-01", "endDate": "2026-09-01"}
    ).json()["data"]["current"][0]["items"]
    assert items == [{"projectTag": "未分配成本", "tagStatus": None, "amount": "100.00"}]


@pytest.mark.django_db
def test_trend_rejects_range_over_366(admin_client, account, resource_types):
    resp = admin_client.get(TREND_URL, {"startDate": "2024-01-01", "endDate": "2026-09-10"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001
