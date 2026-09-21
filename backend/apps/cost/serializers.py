"""成本查询接口序列化层（接口1/2/8）。

职责：① 入参校验并构造 ``CostQueryFilters``；② 出参 camelCase（项目 JSON 约定，
对齐分页 ``pageSize``）；③ 金额两位小数字符串；④ 口径上的 ``None``（环比/预算未配置）
翻译为 ``--``（services.py 约定「由序列化层翻译」，禁止用 0 冒充）；⑤ 财务角色实例ID
屏蔽统一走 ``RoleMaskedSerializerMixin``（permissions.md 强制，不在视图内散落）。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from rest_framework import serializers

from apps.cost.selectors import CostQueryFilters
from common.permissions import RoleMaskedSerializerMixin

_TWO_PLACES = Decimal("0.01")
_DASH = "--"
_TAG_STATUS_CHOICES = ["normal", "unassigned", "conflict"]


def _money_or_dash(value: Any) -> str:
    """金额/比率 → 两位小数字符串；口径上的 None → ``--``。"""
    if value is None:
        return _DASH
    return str(Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def _date_range(start, end) -> dict[str, str]:
    return {"start": start.isoformat(), "end": end.isoformat()}


# ---------- 入参 ----------


class CostQueryInputSerializer(serializers.Serializer):
    """接口1/2/8 共用查询入参（api.md）。"""

    startDate = serializers.DateField()
    endDate = serializers.DateField()
    projectTag = serializers.CharField(required=False, allow_blank=True)
    resourceType = serializers.CharField(required=False, allow_blank=True)
    cloudAccountId = serializers.IntegerField(required=False)
    region = serializers.CharField(required=False, allow_blank=True)
    keyword = serializers.CharField(required=False, allow_blank=True)
    tagStatus = serializers.ChoiceField(required=False, choices=_TAG_STATUS_CHOICES)
    sortField = serializers.CharField(required=False, allow_blank=True)
    sortOrder = serializers.ChoiceField(required=False, choices=["asc", "desc"])

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["endDate"] < attrs["startDate"]:
            raise serializers.ValidationError("endDate 不能早于 startDate")
        return attrs

    def to_filters(self) -> CostQueryFilters:
        d = self.validated_data
        return CostQueryFilters(
            start=d["startDate"],
            end=d["endDate"],
            project_tag=d.get("projectTag") or None,
            resource_type=d.get("resourceType") or None,
            cloud_account_id=d.get("cloudAccountId"),
            region=d.get("region") or None,
            keyword=d.get("keyword") or None,
            tag_status=d.get("tagStatus"),
            sort_field=d.get("sortField") or "totalAmount",
            sort_order=d.get("sortOrder") or "desc",
        )


class TrendQueryInputSerializer(CostQueryInputSerializer):
    """接口8：序列点数上限 366（api.md），超限拒绝。"""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if (attrs["endDate"] - attrs["startDate"]).days + 1 > 366:
            raise serializers.ValidationError("查询区间不得超过 366 天")
        return attrs


# ---------- 接口1 汇总出参 ----------


class SummaryRowSerializer(serializers.Serializer):
    projectTag = serializers.CharField(source="project_tag")
    tagStatus = serializers.CharField(source="tag_status", allow_null=True)
    totalAmount = serializers.SerializerMethodField()
    amountByResourceType = serializers.SerializerMethodField()
    lastPeriodAmount = serializers.SerializerMethodField()
    rate = serializers.SerializerMethodField()
    budgetAmount = serializers.SerializerMethodField()
    budgetRate = serializers.SerializerMethodField()
    overBudget = serializers.BooleanField(source="over_budget")
    budgetIncomplete = serializers.BooleanField(source="budget_incomplete")
    statRange = serializers.SerializerMethodField()
    lastPeriodRange = serializers.SerializerMethodField()

    def get_totalAmount(self, obj) -> str:
        return _money_or_dash(obj.total_amount)

    def get_amountByResourceType(self, obj) -> dict[str, str]:
        return {
            code: _money_or_dash(amount) for code, amount in obj.amount_by_resource_type.items()
        }

    def get_lastPeriodAmount(self, obj) -> str:
        return _money_or_dash(obj.last_period_amount)

    def get_rate(self, obj) -> str:
        return _money_or_dash(obj.rate)

    def get_budgetAmount(self, obj) -> str:
        return _money_or_dash(obj.budget_amount)

    def get_budgetRate(self, obj) -> str:
        return _money_or_dash(obj.budget_rate)

    def get_statRange(self, obj) -> dict[str, str]:
        return _date_range(*self.context["stat_range"])

    def get_lastPeriodRange(self, obj) -> dict[str, str]:
        return _date_range(*self.context["last_period_range"])


# ---------- 接口2 明细出参 ----------


class DetailRowSerializer(serializers.Serializer):
    """明细行（dict 数据源）。instanceId 走角色屏蔽混入（财务返回 null）。"""

    instanceId = serializers.CharField(source="instance_id", allow_null=True)
    resourceType = serializers.CharField(source="resource_type")
    cloudAccountName = serializers.SerializerMethodField()
    region = serializers.CharField(allow_null=True)
    amount = serializers.SerializerMethodField()
    chargeType = serializers.CharField(source="charge_type")
    tagStatus = serializers.CharField(source="tag_status")

    def get_cloudAccountName(self, obj) -> str:
        return obj["cloud_account__account_name"]

    def get_amount(self, obj) -> str:
        return _money_or_dash(obj["amount"])


class MaskedDetailRowSerializer(RoleMaskedSerializerMixin, DetailRowSerializer):
    """财务角色 instanceId → null（屏蔽只在此层发生）。"""


# ---------- 接口8 趋势出参 ----------


class TrendItemSerializer(serializers.Serializer):
    projectTag = serializers.CharField(source="project_tag")
    tagStatus = serializers.CharField(source="tag_status", allow_null=True)
    amount = serializers.SerializerMethodField()

    def get_amount(self, obj) -> str:
        return _money_or_dash(obj.amount)


class TrendPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    items = TrendItemSerializer(many=True)


class TrendResultSerializer(serializers.Serializer):
    current = TrendPointSerializer(many=True)
    compare = TrendPointSerializer(many=True)
    statRange = serializers.SerializerMethodField()
    compareRange = serializers.SerializerMethodField()
    billMonthIncomplete = serializers.BooleanField(source="bill_month_incomplete")

    def get_statRange(self, obj) -> dict[str, str]:
        return _date_range(*obj.stat_range)

    def get_compareRange(self, obj) -> dict[str, str]:
        return _date_range(*obj.compare_range)
