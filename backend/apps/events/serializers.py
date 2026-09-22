"""事件中心序列化层（api.md 接口12 列表 / 接口13 状态更新）。

职责：① 入参校验并构造 ``EventQueryFilters``；② 出参 camelCase（项目 JSON 约定）；
③ 财务角色资源标识字段（resourceId/instanceName）屏蔽统一走 ``RoleMaskedSerializerMixin``
（permissions.md 强制，PRD 4.2）；④ eventTypeName 从 event_type_dict 映射（context 注入，
避免 N+1）；⑤ 时间字段输出 ISO 串（口径上的 None 原样为 null）。
"""

from __future__ import annotations

from rest_framework import serializers

from apps.events.models import CloudEvent
from apps.events.selectors import EventQueryFilters
from common.permissions import RoleMaskedSerializerMixin

_LEVELS = ["info", "warning", "critical"]
_STATUSES = ["unread", "read", "handled", "ignored"]
_ACTIONS = ["read", "handle", "ignore"]
# API 排序字段（camelCase）→ 模型字段名
_SORT_MAP = {
    "occurredAt": "occurred_at",
    "receivedAt": "received_at",
    "eventLevel": "event_level",
    "status": "status",
}


# ---------- 接口12 入参 ----------


class EventQueryInputSerializer(serializers.Serializer):
    """接口12 列表查询入参（eventType 多选由视图层用 getlist 传入真实列表）。"""

    eventType = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    eventLevel = serializers.ChoiceField(required=False, choices=_LEVELS)
    status = serializers.ChoiceField(required=False, choices=_STATUSES)
    startDate = serializers.DateField(required=False)
    endDate = serializers.DateField(required=False)
    resourceType = serializers.CharField(required=False, allow_blank=True)
    projectTag = serializers.CharField(required=False, allow_blank=True)
    cloudAccountId = serializers.IntegerField(required=False)
    keyword = serializers.CharField(required=False, allow_blank=True)
    sortField = serializers.CharField(required=False, allow_blank=True)
    sortOrder = serializers.ChoiceField(required=False, choices=["asc", "desc"])

    def to_filters(self) -> EventQueryFilters:
        d = self.validated_data
        sort_field = _SORT_MAP.get(d.get("sortField") or "", "occurred_at")
        return EventQueryFilters(
            event_types=d.get("eventType") or [],
            event_level=d.get("eventLevel") or None,
            status=d.get("status") or None,
            start=d.get("startDate"),
            end=d.get("endDate"),
            resource_type=d.get("resourceType") or None,
            project_tag=d.get("projectTag") or None,
            cloud_account_id=d.get("cloudAccountId"),
            keyword=d.get("keyword") or None,
            sort_field=sort_field,
            sort_order=d.get("sortOrder") or "desc",
        )


# ---------- 接口12 出参 ----------


class EventRowSerializer(RoleMaskedSerializerMixin, serializers.Serializer):
    """事件行（camelCase）。resourceId/instanceName 对财务角色置 null（屏蔽只在此层）。"""

    id = serializers.IntegerField()
    eventNo = serializers.CharField(source="event_no", allow_null=True)
    eventType = serializers.CharField(source="event_type")
    eventTypeName = serializers.SerializerMethodField()
    eventLevel = serializers.CharField(source="event_level")
    # 出参键名须为 source（api.md 接口12），与 DRF Field.source 同名；运行时正常，
    # 仅 drf-stubs 把基类 source 标注为 str|None，故此处忽略赋值类型告警。
    source = serializers.CharField()  # type: ignore[assignment]
    provider = serializers.CharField(allow_null=True)
    vendorEventName = serializers.CharField(source="vendor_event_name", allow_null=True)
    title = serializers.CharField()
    content = serializers.CharField(allow_null=True)
    resourceType = serializers.CharField(source="resource_type", allow_null=True)
    resourceId = serializers.CharField(source="resource_id", allow_null=True)
    instanceName = serializers.CharField(source="instance_name", allow_null=True)
    projectTag = serializers.CharField(source="project_tag", allow_null=True)
    cloudAccountName = serializers.SerializerMethodField()
    occurredAt = serializers.SerializerMethodField()
    receivedAt = serializers.SerializerMethodField()
    status = serializers.CharField()
    handledBy = serializers.CharField(source="handled_by", allow_null=True)
    handledAt = serializers.SerializerMethodField()

    def get_eventTypeName(self, obj: CloudEvent) -> str | None:
        names: dict[str, str] = self.context.get("type_names", {})
        return names.get(obj.event_type)

    def get_cloudAccountName(self, obj: CloudEvent) -> str | None:
        return obj.cloud_account.account_name if obj.cloud_account else None

    def get_occurredAt(self, obj: CloudEvent) -> str | None:
        return obj.occurred_at.isoformat() if obj.occurred_at else None

    def get_receivedAt(self, obj: CloudEvent) -> str | None:
        return obj.received_at.isoformat() if obj.received_at else None

    def get_handledAt(self, obj: CloudEvent) -> str | None:
        return obj.handled_at.isoformat() if obj.handled_at else None


# ---------- 接口13 入参 ----------


class EventStatusInputSerializer(serializers.Serializer):
    """接口13 状态更新入参：批量 eventIds + 单一 action。"""

    eventIds = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, required=True
    )
    action = serializers.ChoiceField(choices=_ACTIONS)
