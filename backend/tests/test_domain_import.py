"""域名 CSV 导入测试（tasks.md 任务5 / api.md 接口14 / PRD 3.13）。

覆盖：状态推导（3.13-4）、逐行 upsert 幂等、逐行校验回报（不整批失败）、
备注列无 backing 字段被忽略、再导入复活 released_at。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.assets.models import CloudAsset
from apps.assets.services import derive_domain_status, import_domains

TODAY = date(2026, 9, 21)


def _expire(day_offset: int) -> datetime:
    """以 TODAY 正午为基准偏移 day_offset 天的到期时间（UTC 正午避免跨日边界）。"""
    return datetime(2026, 9, 21, 12, 0, tzinfo=UTC) + timedelta(days=day_offset)


# ---------- PRD 3.13-4 状态推导 ----------


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (31, CloudAsset.Status.NORMAL),  # > 30 天 = 正常
        (60, CloudAsset.Status.NORMAL),
        (30, CloudAsset.Status.EXPIRING),  # == 30 天 = 即将到期（≤30）
        (5, CloudAsset.Status.EXPIRING),
        (0, CloudAsset.Status.EXPIRING),  # 今天到期 = 即将到期
        (-1, CloudAsset.Status.EXPIRED),  # 已过期
        (-30, CloudAsset.Status.EXPIRED),
    ],
)
def test_derive_domain_status_by_days(offset: int, expected: str):
    assert derive_domain_status(_expire(offset), today=TODAY) == expected


def test_derive_domain_status_none_is_unknown():
    assert derive_domain_status(None, today=TODAY) == CloudAsset.Status.UNKNOWN


# ---------- import_domains：逐行 upsert + 校验回报 ----------


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "域名": "example.com",
        "注册商": "阿里云",
        "到期时间": "2027-01-15",
        "实名状态": "已实名",
        "DNS 服务器": "dns1.hichina.com,dns2.hichina.com",
        "自动续费": "是",
        "项目标签": "projA",
        "备注": "随便写点什么都行",
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
def test_import_single_valid_row_persists_asset():
    result = import_domains([_row()], today=TODAY)
    assert result.success_count == 1
    assert result.errors == []
    asset = CloudAsset.objects.get()
    assert asset.resource_type == "domain"
    assert asset.instance_id == "example.com"
    assert asset.instance_name == "example.com"  # 3.13-2：instance_name 同存域名
    assert asset.registrar == "阿里云"
    assert asset.realname_status == "已实名"
    assert asset.dns_servers == "dns1.hichina.com,dns2.hichina.com"
    assert asset.auto_renew is True
    assert asset.project_tag == "projA"
    assert asset.status == CloudAsset.Status.NORMAL  # 2027-01-15 距今 > 30 天
    assert asset.cloud_account_id is None  # 域名归属账号可空
    assert asset.released_at is None
    assert asset.first_seen_at is not None and asset.last_seen_at is not None


@pytest.mark.django_db
def test_import_persists_remark():
    """「备注」列落库到 CloudAsset.remark（database.md 表10 V1.22 补列）。"""
    result = import_domains([_row(备注="续费走财务审批")], today=TODAY)
    assert result.success_count == 1
    assert CloudAsset.objects.get().remark == "续费走财务审批"


@pytest.mark.django_db
def test_import_empty_remark_is_none():
    result = import_domains([_row(备注="  ")], today=TODAY)
    assert result.success_count == 1
    assert CloudAsset.objects.get().remark is None


@pytest.mark.django_db
def test_reimport_updates_remark():
    import_domains([_row(备注="旧备注")], today=TODAY)
    import_domains([_row(备注="新备注")], today=TODAY)
    assert CloudAsset.objects.count() == 1
    assert CloudAsset.objects.get().remark == "新备注"


@pytest.mark.django_db
def test_import_duplicate_domain_updates_not_inserts():
    import_domains([_row(**{"注册商": "阿里云", "项目标签": "projA"})], today=TODAY)
    result = import_domains([_row(**{"注册商": "西部数码", "项目标签": "projB"})], today=TODAY)
    assert result.success_count == 1
    assert CloudAsset.objects.count() == 1  # uk_asset(NULL,'domain',域名) → 更新而非新增
    asset = CloudAsset.objects.get()
    assert asset.registrar == "西部数码"
    assert asset.project_tag == "projB"


@pytest.mark.django_db
def test_import_invalid_domain_format_reports_row_and_skips():
    result = import_domains([_row(域名="not a domain")], today=TODAY)
    assert result.success_count == 0
    assert CloudAsset.objects.count() == 0
    assert len(result.errors) == 1
    assert result.errors[0].row == 2  # 表头为第 1 行，首条数据为第 2 行
    assert "域名" in result.errors[0].reason


@pytest.mark.django_db
def test_import_missing_domain_reports_row():
    result = import_domains([_row(域名="  ")], today=TODAY)
    assert result.success_count == 0
    assert result.errors[0].row == 2
    assert "域名" in result.errors[0].reason


@pytest.mark.django_db
def test_import_bad_expire_time_reports_row():
    result = import_domains([_row(到期时间="2027年1月")], today=TODAY)
    assert result.success_count == 0
    assert CloudAsset.objects.count() == 0
    assert "到期时间" in result.errors[0].reason


@pytest.mark.django_db
def test_import_bad_auto_renew_reports_row():
    result = import_domains([_row(自动续费="maybe")], today=TODAY)
    assert result.success_count == 0
    assert "自动续费" in result.errors[0].reason


@pytest.mark.django_db
def test_import_empty_expire_time_is_unknown_status_not_error():
    result = import_domains([_row(到期时间="")], today=TODAY)
    assert result.success_count == 1
    assert result.errors == []
    assert CloudAsset.objects.get().status == CloudAsset.Status.UNKNOWN


@pytest.mark.django_db
def test_import_partial_success_does_not_rollback():
    """混合正确/错误行：正确行入库、错误行逐行回报，不整批失败（api.md 接口14）。"""
    rows = [
        _row(域名="ok1.com"),
        _row(域名="bad domain"),  # 第 3 行错误
        _row(域名="ok2.com", 到期时间="2026-10-01"),  # 距今 10 天 → expiring
    ]
    result = import_domains(rows, today=TODAY)
    assert result.success_count == 2
    assert [e.row for e in result.errors] == [3]
    assert CloudAsset.objects.count() == 2
    assert CloudAsset.objects.get(instance_id="ok2.com").status == CloudAsset.Status.EXPIRING


@pytest.mark.django_db
def test_import_bool_variants_parsed():
    rows = [
        _row(域名="a.com", 自动续费="true"),
        _row(域名="b.com", 自动续费="否"),
        _row(域名="c.com", 自动续费=""),  # 空 → None
    ]
    result = import_domains(rows, today=TODAY)
    assert result.success_count == 3
    assert CloudAsset.objects.get(instance_id="a.com").auto_renew is True
    assert CloudAsset.objects.get(instance_id="b.com").auto_renew is False
    assert CloudAsset.objects.get(instance_id="c.com").auto_renew is None


@pytest.mark.django_db
def test_import_expires_soon_derives_expiring_and_expired():
    rows = [
        _row(域名="soon.com", 到期时间="2026-10-01"),  # 10 天
        _row(域名="gone.com", 到期时间="2026-09-01"),  # 已过期
    ]
    import_domains(rows, today=TODAY)
    assert CloudAsset.objects.get(instance_id="soon.com").status == CloudAsset.Status.EXPIRING
    assert CloudAsset.objects.get(instance_id="gone.com").status == CloudAsset.Status.EXPIRED


@pytest.mark.django_db
def test_reimport_revives_released_domain():
    import_domains([_row(域名="revive.com")], today=TODAY)
    CloudAsset.objects.filter(instance_id="revive.com").update(released_at=_expire(0))
    result = import_domains([_row(域名="revive.com")], today=TODAY)
    assert result.success_count == 1
    assert CloudAsset.objects.get(instance_id="revive.com").released_at is None


# ---------- Django Admin 单条维护复用状态推导（tasks.md 任务5）----------


@pytest.mark.django_db
def test_admin_save_derives_domain_status():
    """Admin 保存域名时 status 由 expire_time 推导，与 CSV 导入共用同一口径。"""
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory

    from apps.assets.admin import CloudAssetAdmin

    admin = CloudAssetAdmin(CloudAsset, AdminSite())
    asset = CloudAsset(
        resource_type="domain",
        instance_id="admin.com",
        instance_name="admin.com",
        expire_time=_expire(10),  # 距今 10 天 → expiring
        status=CloudAsset.Status.UNKNOWN,
    )
    admin.save_model(RequestFactory().get("/"), obj=asset, form=None, change=False)
    assert CloudAsset.objects.get(instance_id="admin.com").status == CloudAsset.Status.EXPIRING


@pytest.mark.django_db
def test_admin_save_leaves_non_domain_status_untouched():
    """非域名资源（如 ECS）状态由同步任务映射，Admin 不重导。"""
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory

    from apps.assets.admin import CloudAssetAdmin

    admin = CloudAssetAdmin(CloudAsset, AdminSite())
    asset = CloudAsset(
        resource_type="ecs",
        instance_id="i-123",
        expire_time=_expire(10),
        status=CloudAsset.Status.RUNNING,
    )
    admin.save_model(RequestFactory().get("/"), obj=asset, form=None, change=False)
    assert CloudAsset.objects.get(instance_id="i-123").status == CloudAsset.Status.RUNNING
