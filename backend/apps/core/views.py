"""仪表盘聚合接口视图（api.md 接口9）。

一次返回 cards/trend/syncStatus 三块以减少首页请求数（PRD 3.10）；无入参，服务端
按当前本地日取默认区间（trend 近 30 天，按 resource_type 堆叠，复用接口8 结构）。
三个角色均可访问（PRD 3.10-4），仅要求登录；页面不展示任何实例级字段。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.selectors import dashboard_cards, sync_status
from apps.core.serializers import cards_payload, sync_status_payload
from apps.cost.selectors import CostQueryFilters, query_resource_trend
from apps.cost.serializers import TrendResultSerializer

_TREND_DAYS = 30


class DashboardView(APIView):
    permission_classes = (IsAuthenticated,)  # type: ignore[assignment]

    def get(self, request: Request) -> Response:
        today = timezone.localdate()
        trend_start = today - timedelta(days=_TREND_DAYS - 1)
        trend = query_resource_trend(CostQueryFilters(start=trend_start, end=today), today=today)
        data: dict[str, Any] = {
            "cards": cards_payload(dashboard_cards(today)),
            "trend": TrendResultSerializer(trend, context={"request": request}).data,
            "syncStatus": sync_status_payload(sync_status()),
        }
        return Response(data)
