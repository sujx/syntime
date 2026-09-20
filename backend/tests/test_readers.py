"""§5.2 两级回退读取器单测（依赖 DB，随迁移种子数据验证）。

运行前置：本地 PostgreSQL 可用且已 migrate（含 0002 种子迁移）。
"""

import logging
from datetime import date
from decimal import Decimal

import pytest

from apps.billing.models import ExchangeRate, ResourceTypeDict
from apps.core.models import PlatformSetting
from apps.events.models import EventTypeDict, VendorMapping
from common.readers import (
    PLATFORM_SETTING_DEFAULTS,
    MissingDictEntryError,
    get_exchange_rate,
    get_platform_setting,
    get_vendor_mapping,
    require_event_type,
    require_resource_type,
)

# ---------- platform_setting：配置表 → 代码兜底 ----------


@pytest.mark.django_db
def test_setting_table_takes_precedence_over_default():
    # 种子迁移已写入默认 14；覆盖为 30 后应读到表值（表优先于代码默认）
    PlatformSetting.objects.update_or_create(
        setting_key="idle_stopped_days", defaults={"setting_value": 30}
    )
    assert get_platform_setting("idle_stopped_days") == 30
    assert PLATFORM_SETTING_DEFAULTS["idle_stopped_days"] == 14


@pytest.mark.django_db
def test_setting_falls_back_to_code_default(caplog):
    # 删除种子行 → 取代码默认值并记日志（PRD 2.6-3 两级回退）
    PlatformSetting.objects.filter(setting_key="audit_retention_months").delete()
    with caplog.at_level(logging.INFO):
        value = get_platform_setting("audit_retention_months")
    assert value == PLATFORM_SETTING_DEFAULTS["audit_retention_months"] == 12
    assert "audit_retention_months" in caplog.text


@pytest.mark.django_db
def test_setting_unknown_key_raises():
    with pytest.raises(KeyError):
        get_platform_setting("not_a_real_key")


@pytest.mark.django_db
def test_seed_migration_populates_all_default_keys():
    """§5.2：预置配置键随 0002 种子迁移落库，值等于代码默认值。"""
    for key, default in PLATFORM_SETTING_DEFAULTS.items():
        assert PlatformSetting.objects.filter(setting_key=key).exists(), key
        assert get_platform_setting(key) == default


@pytest.mark.django_db
def test_require_resource_type_found():
    # 用非种子 code，避免与 0002 种子行撞唯一键
    ResourceTypeDict.objects.create(code="slb", display_name="负载均衡")
    assert require_resource_type("slb").code == "slb"


@pytest.mark.django_db
def test_require_resource_type_missing_raises_and_logs(caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(MissingDictEntryError):
        require_resource_type("ghost")
    assert "ghost" in caplog.text


@pytest.mark.django_db
def test_require_event_type_found_and_missing():
    EventTypeDict.objects.create(code="custom_evt", display_name="自定义", default_level="info")
    assert require_event_type("custom_evt").default_level == "info"
    with pytest.raises(MissingDictEntryError):
        require_event_type("nope")


@pytest.mark.django_db
def test_vendor_mapping_enabled_only():
    VendorMapping.objects.create(
        mapping_kind="resource_type",
        provider="aliyun",
        vendor_code="ecs",
        standard_code="ecs",
        enabled=True,
    )
    VendorMapping.objects.create(
        mapping_kind="resource_type",
        provider="aliyun",
        vendor_code="disabled_x",
        standard_code="x",
        enabled=False,
    )
    assert get_vendor_mapping("resource_type", "aliyun", "ecs").standard_code == "ecs"
    # 停用行视同缺失（调用方据此原样保留厂商值）
    with pytest.raises(MissingDictEntryError):
        get_vendor_mapping("resource_type", "aliyun", "disabled_x")
    with pytest.raises(MissingDictEntryError):
        get_vendor_mapping("resource_type", "aliyun", "absent")


@pytest.mark.django_db
def test_exchange_rate_found_and_missing():
    ExchangeRate.objects.create(
        currency="USD", rate_date=date(2026, 9, 1), rate_to_cny=Decimal("7.10000000")
    )
    assert get_exchange_rate("USD", date(2026, 9, 1)) == Decimal("7.10000000")
    with pytest.raises(MissingDictEntryError):
        get_exchange_rate("USD", date(2026, 9, 2))


@pytest.mark.django_db
def test_dict_seed_migrations_populate_core_entries():
    """§5.2：资源类型/事件类型字典种子随 0002 迁移落库。"""
    for code in ("ecs", "rds", "eip", "nat", "domain"):
        assert ResourceTypeDict.objects.filter(code=code).exists(), code
    for code in (
        "arrears",
        "traffic_exceed",
        "renewed",
        "stopped",
        "expiring",
        "expired",
        "budget_overrun",
    ):
        assert EventTypeDict.objects.filter(code=code).exists(), code
    # 停机=高危、续费=提示（PRD 3.12-5 默认级别）
    assert require_event_type("stopped").default_level == "critical"
    assert require_event_type("renewed").default_level == "info"
