"""事件中心接口视图（api.md 接口12 列表 / 接口13 状态更新）。

列表：三角色均可查看（仅要求登录），财务字段级屏蔽在序列化层；排序/筛选在 selector
全量执行，分页走全局 ``ResultPaginator``，另附全局 ``unreadCount``（页头角标）。
状态更新：限成本管理员与云运维（``IsEventOperator``，财务→40300）；批量按 action 改
``status`` 与 ``handled_by/handled_at``，并写 ``audit_log(action=event_handle)``。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.models import CloudEvent, EventTypeDict
from apps.events.selectors import count_unread, list_events
from apps.events.serializers import (
    EventQueryInputSerializer,
    EventRowSerializer,
    EventStatusInputSerializer,
)
from common.api.pagination import ResultPaginator
from common.audit import record_audit
from common.permissions import IsEventOperator, get_role

# action → (目标状态, 是否记录处理人/处理时间)
_ACTION_MAP = {
    "read": (CloudEvent.Status.READ, False),
    "handle": (CloudEvent.Status.HANDLED, True),
    "ignore": (CloudEvent.Status.IGNORED, True),
}


class EventListView(APIView):
    permission_classes = (IsAuthenticated,)  # type: ignore[assignment]

    def get(self, request: Request) -> Response:
        params = self._query_dict(request)
        inp = EventQueryInputSerializer(data=params)
        inp.is_valid(raise_exception=True)
        queryset = list_events(inp.to_filters())

        paginator = ResultPaginator()
        page = paginator.paginate_queryset(queryset, request, self)
        type_names = dict(EventTypeDict.objects.values_list("code", "display_name"))
        rows = EventRowSerializer(
            page, many=True, context={"request": request, "type_names": type_names}
        ).data
        data: dict[str, Any] = OrderedDict(
            paginator.get_paginated_response(cast("list[Any]", rows)).data
        )
        data["unreadCount"] = count_unread()
        return Response(data)

    @staticmethod
    def _query_dict(request: Request) -> dict[str, Any]:
        """把 QueryDict 摊平为普通 dict，eventType 用 getlist 保留多选。"""
        qp = request.query_params
        return {key: qp.getlist(key) if key == "eventType" else qp.get(key) for key in qp}


class EventStatusUpdateView(APIView):
    permission_classes = (IsAuthenticated, IsEventOperator)  # type: ignore[assignment]

    def post(self, request: Request) -> Response:
        inp = EventStatusInputSerializer(data=request.data)
        inp.is_valid(raise_exception=True)
        action = inp.validated_data["action"]
        event_ids = inp.validated_data["eventIds"]
        status, stamp_handler = _ACTION_MAP[action]

        qs = CloudEvent.objects.filter(pk__in=event_ids)
        update_fields: dict[str, Any] = {"status": status}
        if stamp_handler:
            update_fields["handled_by"] = request.user.username
            update_fields["handled_at"] = timezone.now()
        updated = qs.update(**update_fields)

        record_audit(
            "event_handle",
            operator=request.user.username,
            role=get_role(request.user),
            params={"action": action, "eventIds": event_ids, "status": status},
            result="success",
            client_ip=_client_ip(request),
        )
        return Response({"updated": updated})


def _client_ip(request: Request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return str(forwarded).split(",")[0].strip()
    remote = request.META.get("REMOTE_ADDR")
    return str(remote) if remote else None
