"""§6 事件与厂商消息去重单测（uk_event_dedup / uk_vendor_msg / F050 / F056）。"""

import pytest

from apps.events.models import CloudEvent, VendorMessageLog
from apps.events.services import record_vendor_message, upsert_event


def _event_fields(**overrides):
    fields = {
        "event_type": "stopped",
        "event_level": "critical",
        "source": "rule",
        "title": "实例 i-1 已停机",
        "resource_type": "ecs",
        "resource_id": "i-1",
    }
    fields.update(overrides)
    return fields


@pytest.mark.django_db
def test_upsert_event_dedup_by_key():
    first, created = upsert_event(dedup_key="stopped:i-1:20260901", **_event_fields())
    assert created is True
    again, created_again = upsert_event(
        dedup_key="stopped:i-1:20260901", **_event_fields(title="重复检测的同一事件")
    )
    assert created_again is False
    assert again.pk == first.pk
    assert CloudEvent.objects.count() == 1
    # 已存在事件不回写：状态流转走事件处理接口，不被重复消息覆盖
    assert again.title == "实例 i-1 已停机"


@pytest.mark.django_db
def test_upsert_event_new_key_after_recovery():
    """F050：恢复后再次停机 → 新 dedup_key 产生新事件。"""
    upsert_event(dedup_key="stopped:i-1:20260901", **_event_fields())
    upsert_event(dedup_key="stopped:i-1:20260915", **_event_fields())
    assert CloudEvent.objects.count() == 2


@pytest.mark.django_db
def test_record_vendor_message_dedup_by_message_id():
    first, created = record_vendor_message(
        provider="aliyun",
        message_id="m-1",
        raw_payload='{"code":"InstanceStop"}',
    )
    assert created is True
    again, created_again = record_vendor_message(
        provider="aliyun",
        message_id="m-1",
        raw_payload='{"code":"InstanceStop"}',
    )
    assert created_again is False
    assert again.pk == first.pk
    assert VendorMessageLog.objects.count() == 1


@pytest.mark.django_db
def test_record_vendor_message_same_id_different_provider():
    record_vendor_message(provider="aliyun", message_id="m-1", raw_payload="{}")
    _, created = record_vendor_message(provider="tencent", message_id="m-1", raw_payload="{}")
    assert created is True  # uk 为 (provider, message_id)，跨厂商不互斥
    assert VendorMessageLog.objects.count() == 2


@pytest.mark.django_db
def test_message_to_event_linking_via_dedup():
    """F056 组合链路：同消息建事件，重复消息只补关联、不重复建事件。"""
    event, _ = upsert_event(dedup_key="arrears:acc1", **_event_fields())
    log, _ = record_vendor_message(
        provider="aliyun",
        message_id="m-2",
        raw_payload="{}",
        mapped_event_type="arrears",
        mapped_status="mapped",
        cloud_event=event,
    )
    assert log.cloud_event_id == event.pk
    # 重复接收同一消息：流水不重复、事件不重复
    _, created_log = record_vendor_message(provider="aliyun", message_id="m-2", raw_payload="{}")
    assert created_log is False
    assert CloudEvent.objects.count() == 1
