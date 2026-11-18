"""闲置清单序列化层（api.md 接口16）。

① 入参校验并构造 `IdleQueryFilters`（排序键白名单在此映射，未知键回落默认，
不透传给查询层）；② 出参 camelCase；③ `expireTime` 输出 ISO 串，None 原样 null。
本接口财务角色在**接口级**就被拦为 40300（PRD 3.14-7），拿不到 body，
故不挂 `RoleMaskedSerializerMixin`——为不可能的场景写代码即冗余。
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.assets.idle_rules import IDLE_TYPES
from apps.assets.selectors import DEFAULT_SORT_FIELD, IdleQueryFilters, IdleRow

# API 排序字段（camelCase）→ 模型字段名（与 selectors._SORTABLE 一一对应）
_SORT_MAP = {
    "instanceId": "instance_id",
    "resourceType": "resource_type",
    "status": "status",
    "region": "region",
    "projectTag": "project_tag",
    "expireTime": "expire_time",
}


class IdleQueryInputSerializer(serializers.Serializer):
    """接口16 入参。`idleType` 多选由视图层用 getlist 传入真实列表。"""

    idleType = serializers.ListField(
        child=serializers.ChoiceField(choices=IDLE_TYPES), required=False, allow_empty=True
    )
    resourceType = serializers.CharField(required=False, allow_blank=True)
    cloudAccountId = serializers.IntegerField(required=False)
    region = serializers.CharField(required=False, allow_blank=True)
    projectTag = serializers.CharField(required=False, allow_blank=True)
    keyword = serializers.CharField(required=False, allow_blank=True)
    sortField = serializers.CharField(required=False, allow_blank=True)
    sortOrder = serializers.ChoiceField(required=False, choices=["asc", "desc"])

    def to_filters(self) -> IdleQueryFilters:
        d: dict[str, Any] = self.validated_data
        return IdleQueryFilters(
            idle_types=list(d.get("idleType") or []),
            resource_type=d.get("resourceType") or None,
            cloud_account_id=d.get("cloudAccountId"),
            region=d.get("region") or None,
            project_tag=d.get("projectTag") or None,
            keyword=d.get("keyword") or None,
            sort_field=_SORT_MAP.get(d.get("sortField") or "", DEFAULT_SORT_FIELD),
            sort_order=d.get("sortOrder") or "asc",
        )


class IdleRowSerializer(serializers.Serializer):
    """接口16 单行：资产字段 + 判定依据（idleType / idleReason / keyMetric）。"""

    instanceId = serializers.CharField(source="asset.instance_id")
    instanceName = serializers.CharField(source="asset.instance_name", allow_null=True)
    resourceType = serializers.CharField(source="asset.resource_type")
    cloudAccountName = serializers.CharField(source="account_name", allow_null=True)
    region = serializers.CharField(source="asset.region", allow_null=True)
    projectTag = serializers.CharField(source="asset.project_tag", allow_null=True)
    status = serializers.CharField(source="asset.status")
    idleType = serializers.CharField(source="verdict.idle_type")
    idleReason = serializers.CharField(source="verdict.reason")
    keyMetric = serializers.DictField(child=serializers.IntegerField(), source="verdict.key_metric")
    expireTime = serializers.SerializerMethodField()

    def get_expireTime(self, obj: IdleRow) -> str | None:
        return obj.asset.expire_time.isoformat() if obj.asset.expire_time else None
