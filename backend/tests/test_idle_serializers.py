"""接口16 序列化层：入参 camelCase → IdleQueryFilters、出参 camelCase 与时间格式。"""

from __future__ import annotations

from datetime import UTC, datetime

from apps.assets.idle_rules import IDLE_EIP_UNBOUND, IdleVerdict
from apps.assets.models import CloudAsset
from apps.assets.selectors import IdleQueryFilters, IdleRow
from apps.assets.serializers import IdleQueryInputSerializer, IdleRowSerializer


def _row(**overrides: object) -> IdleRow:
    base: dict[str, object] = {
        "resource_type": "eip",
        "instance_id": "eip-1",
        "instance_name": "出口 EIP",
        "status": CloudAsset.Status.UNBOUND,
        "region": "cn-hangzhou",
        "project_tag": "项目A",
        "expire_time": None,
    }
    base.update(overrides)
    asset = CloudAsset(**base)
    return IdleRow(
        asset=asset,
        verdict=IdleVerdict(IDLE_EIP_UNBOUND, "EIP 处于未绑定状态"),
        account_name="prod-main",
    )


def test_input_defaults() -> None:
    serializer = IdleQueryInputSerializer(data={})
    assert serializer.is_valid(), serializer.errors
    assert serializer.to_filters() == IdleQueryFilters()


def test_input_maps_camel_case() -> None:
    serializer = IdleQueryInputSerializer(
        data={
            "idleType": [IDLE_EIP_UNBOUND],
            "resourceType": "eip",
            "cloudAccountId": "7",
            "region": "cn-hangzhou",
            "projectTag": "项目A",
            "keyword": "eip",
            "sortField": "instanceId",
            "sortOrder": "desc",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.to_filters() == IdleQueryFilters(
        idle_types=[IDLE_EIP_UNBOUND],
        resource_type="eip",
        cloud_account_id=7,
        region="cn-hangzhou",
        project_tag="项目A",
        keyword="eip",
        sort_field="instance_id",
        sort_order="desc",
    )


def test_input_rejects_unknown_idle_type_and_sort_field() -> None:
    assert not IdleQueryInputSerializer(data={"idleType": ["nope"]}).is_valid()
    # 排序键不认识的不能变成 SQL 注入面：回落默认键而不是原样透传
    serializer = IdleQueryInputSerializer(data={"sortField": "drop table"})
    assert serializer.is_valid()
    assert serializer.to_filters().sort_field == "expire_time"


def test_row_output_camel_case_and_nulls() -> None:
    data = IdleRowSerializer(_row()).data
    assert set(data) == {
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
    assert data["instanceId"] == "eip-1"
    assert data["cloudAccountName"] == "prod-main"
    assert data["idleType"] == IDLE_EIP_UNBOUND
    assert data["keyMetric"] == {}
    assert data["expireTime"] is None


def test_row_output_formats_expire_time() -> None:
    moment = datetime(2026, 11, 18, 4, 0, tzinfo=UTC)
    data = IdleRowSerializer(_row(expire_time=moment)).data
    assert data["expireTime"] == moment.isoformat()
