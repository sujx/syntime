"""事件与厂商消息幂等入库（engineering-conventions §6：uk_event_dedup / uk_vendor_msg）。

去重语义（F050 / F056）：

- 厂商消息按 ``(provider, message_id)`` 不重复入库，重复回调幂等返回既有行；
- 事件按 ``dedup_key`` 去重——同一告警未恢复前重复检测/重复消息不产生第二条
  事件；恢复后再次发生由调用方生成新 ``dedup_key``（含时间戳，F050）。

``get_or_create`` 依赖数据库唯一键兜底并发（§6：唯一键优先于代码判断），
命中已存在键时 ``created=False``，调用方据此把消息流水标记为 duplicated。
"""

from __future__ import annotations

from typing import Any

from apps.events.models import CloudEvent, VendorMessageLog


def upsert_event(**fields: Any) -> tuple[CloudEvent, bool]:
    """按 dedup_key 去重落事件，返回 (event, created)。

    除 ``dedup_key`` 外的字段全部经 ``fields`` 传入（新事件时作为初始值，
    已存在事件不回写——状态流转走事件处理接口，不靠重复消息覆盖）。
    """
    dedup_key = fields.pop("dedup_key")
    event, created = CloudEvent.objects.get_or_create(dedup_key=dedup_key, defaults=fields)
    return event, created


def record_vendor_message(**fields: Any) -> tuple[VendorMessageLog, bool]:
    """按 (provider, message_id) 去重落厂商消息流水，返回 (log, created)。

    全量流水含重复消息的去重语义：重复接收不二次入库（uk_vendor_msg 拦截），
    幂等返回既有行与 ``created=False``，调用方据此置 ``mapped_status=duplicated``。
    """
    provider = fields.pop("provider")
    message_id = fields.pop("message_id")
    log, created = VendorMessageLog.objects.get_or_create(
        provider=provider, message_id=message_id, defaults=fields
    )
    return log, created
