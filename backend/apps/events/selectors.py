"""事件中心读路径（api.md 接口12；engineering-conventions §2：selectors 只做读）。

数据源 ``cloud_event``（含厂商消息 / 平台自算 / 手工补录三来源）。筛选与排序在
服务端全量执行（api.md 接口12：排序在服务端全量执行，默认按 ``occurred_at`` 倒序），
分页由视图层的 ``ResultPaginator`` 完成。财务角色对资源标识字段的屏蔽在序列化层，
本层不感知角色。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q, QuerySet

from apps.events.models import CloudEvent

# 允许排序的字段白名单（API 传入的 camelCase 已在序列化层映射为模型字段名）
_SORTABLE = {"occurred_at", "received_at", "event_level", "status"}


@dataclass(frozen=True)
class EventQueryFilters:
    """接口12 查询条件（已由序列化层校验）。"""

    event_types: list[str] = field(default_factory=list)
    event_level: str | None = None
    status: str | None = None
    start: date | None = None
    end: date | None = None
    resource_type: str | None = None
    project_tag: str | None = None
    cloud_account_id: int | None = None
    keyword: str | None = None
    sort_field: str = "occurred_at"
    sort_order: str = "desc"


def list_events(filters: EventQueryFilters) -> QuerySet[CloudEvent]:
    """按条件筛选 + 排序返回事件 QuerySet（不分页，交给视图层分页器）。"""
    qs = CloudEvent.objects.select_related("cloud_account").all()

    if filters.event_types:
        qs = qs.filter(event_type__in=filters.event_types)
    if filters.event_level:
        qs = qs.filter(event_level=filters.event_level)
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.resource_type:
        qs = qs.filter(resource_type=filters.resource_type)
    if filters.project_tag:
        qs = qs.filter(project_tag=filters.project_tag)
    if filters.cloud_account_id is not None:
        qs = qs.filter(cloud_account_id=filters.cloud_account_id)
    if filters.start is not None:
        qs = qs.filter(occurred_at__date__gte=filters.start)
    if filters.end is not None:
        qs = qs.filter(occurred_at__date__lte=filters.end)
    if filters.keyword:
        kw = filters.keyword
        qs = qs.filter(
            Q(title__icontains=kw)
            | Q(content__icontains=kw)
            | Q(instance_name__icontains=kw)
            | Q(resource_id__icontains=kw)
        )

    sort_field = filters.sort_field if filters.sort_field in _SORTABLE else "occurred_at"
    ordering = sort_field if filters.sort_order == "asc" else f"-{sort_field}"
    # 次序稳定的次级排序键，避免同值行在分页间跳动
    return qs.order_by(ordering, "-pk")


def count_unread() -> int:
    """全局未读事件数（事件中心页头角标，不随列表筛选变化）。"""
    return CloudEvent.objects.filter(status=CloudEvent.Status.UNREAD).count()
