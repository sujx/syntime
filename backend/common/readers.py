"""两级回退读取器（engineering-conventions §5.2，PRD 2.6）。

- ``platform_setting``：配置表 → 代码内兜底默认值（键缺省时取默认并记日志）；
- 字典四表（resource_type_dict / event_type_dict / vendor_mapping / exchange_rate）：
  字典表 → **报错并记日志**（MissingDictEntryError），不静默取空值。

预置配置键与字典种子数据随各 app 的 seed migration 落库；
本模块的 ``PLATFORM_SETTING_DEFAULTS`` 是默认值的唯一来源，migration 直接引用。
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from apps.billing.models import ExchangeRate, ResourceTypeDict
from apps.core.models import PlatformSetting
from apps.events.models import EventTypeDict, VendorMapping

logger = logging.getLogger(__name__)

# 预置配置键与代码内兜底默认值（database.md 表 15；JSONField 按原生 JSON 类型存取）
PLATFORM_SETTING_DEFAULTS: dict[str, Any] = {
    # 带宽费用突增阈值（比例，0.3 = 环比涨 30% 记异常）
    "bandwidth_spike_threshold": 0.3,
    # 到期提醒档位（天）：T-30 / T-7 / T-1（PRD 3.12-8）
    "expire_notice_days": [30, 7, 1],
    # 未分配成本治理目标占比（Q3：≤5%）
    "unallocated_ratio_target": 0.05,
    # 同步调度（tasks.md 任务 1/2/4：账单 02:00、资产 02:30、每月 3 日全量重算）
    "sync_cron": {
        "bill_sync": "0 2 * * *",
        "asset_sync": "30 2 * * *",
        "reaggregate_monthly": "0 3 3 * *",
    },
    # 审计日志保留月数（Q4：在线 3 个月 + 归档至 12 个月）
    "audit_retention_months": 12,
    # 各事件类型默认级别覆盖（默认空：以 event_type_dict.default_level 为准）
    "event_level_defaults": {},
    # 按量付费停机闲置判定天数（Q17，PRD 3.14-1）
    "idle_stopped_days": 14,
}

_MISSING = object()


class MissingDictEntryError(LookupError):
    """字典表查不到条目：不静默取空值，由调用方决定兜底行为（如原样保留厂商值）。"""


def get_platform_setting(key: str) -> Any:
    """读取平台配置：platform_setting 表 → 代码内兜底默认值（PRD 2.6-3）。

    键既不在表中也不在默认值表时抛 KeyError（属编码错误，不应静默）。
    """
    row = PlatformSetting.objects.filter(setting_key=key).first()
    if row is not None:
        return row.setting_value

    default = PLATFORM_SETTING_DEFAULTS.get(key, _MISSING)
    if default is _MISSING:
        raise KeyError(f"platform_setting 未知配置键：{key}（无表记录亦无代码默认值）")
    logger.info("platform_setting 键 %s 未配置，使用代码默认值 %r", key, default)
    return default


def require_resource_type(code: str) -> ResourceTypeDict:
    """资源类型字典读取：查不到抛 MissingDictEntryError 并记日志。"""
    row = ResourceTypeDict.objects.filter(code=code).first()
    if row is None:
        logger.warning("resource_type_dict 缺少 code=%s", code)
        raise MissingDictEntryError(f"resource_type_dict 缺少 code={code}")
    return row


def require_event_type(code: str) -> EventTypeDict:
    """事件类型字典读取：查不到抛 MissingDictEntryError 并记日志。"""
    row = EventTypeDict.objects.filter(code=code).first()
    if row is None:
        logger.warning("event_type_dict 缺少 code=%s", code)
        raise MissingDictEntryError(f"event_type_dict 缺少 code={code}")
    return row


def get_vendor_mapping(mapping_kind: str, provider: str, vendor_code: str) -> VendorMapping:
    """厂商标准映射读取（仅取启用行）。

    查不到抛 MissingDictEntryError——调用方应捕获后**原样保留厂商值并记日志**，
    不静默丢弃（database.md 表 14-③、PRD 3.12-8.1）。
    """
    row = VendorMapping.objects.filter(
        mapping_kind=mapping_kind,
        provider=provider,
        vendor_code=vendor_code,
        enabled=True,
    ).first()
    if row is None:
        logger.warning(
            "vendor_mapping 缺少 kind=%s provider=%s vendor_code=%s",
            mapping_kind,
            provider,
            vendor_code,
        )
        raise MissingDictEntryError(
            f"vendor_mapping 缺少 kind={mapping_kind} provider={provider} vendor_code={vendor_code}"
        )
    return row


def get_exchange_rate(currency: str, rate_date: date) -> Decimal:
    """汇率读取：按币种 + 汇率日精确查表，查不到抛 MissingDictEntryError。

    账单入库缺失汇率时不阻断入库（database.md 表 9），由调用方标记后补录回溯。
    """
    row = ExchangeRate.objects.filter(currency=currency, rate_date=rate_date).first()
    if row is None:
        logger.warning("exchange_rate 缺少 currency=%s rate_date=%s", currency, rate_date)
        raise MissingDictEntryError(f"exchange_rate 缺少 currency={currency} rate_date={rate_date}")
    return row.rate_to_cny
