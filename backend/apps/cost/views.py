"""成本查询接口视图（接口1 汇总 / 接口2 明细 / 接口8 趋势）。

三角色均可查看（PRD 4.1 权限矩阵），故仅要求登录；财务字段级屏蔽在序列化层。
统一信封由全局 ``ResultEnvelopeRenderer`` 包装，分页用全局 ``ResultPaginator``。
排序在 selector 的全量结果上完成（api.md 接口1：先聚合→排序→分页）。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cost.selectors import list_bill_details, query_cost_trend, summarize_project_costs
from apps.cost.serializers import (
    CostQueryInputSerializer,
    MaskedDetailRowSerializer,
    SummaryRowSerializer,
    TrendQueryInputSerializer,
    TrendResultSerializer,
    _money_or_dash,
)
from common.api.pagination import ResultPaginator


class CostSummaryView(APIView):
    permission_classes = (IsAuthenticated,)  # type: ignore[assignment]

    def get(self, request: Request) -> Response:
        inp = CostQueryInputSerializer(data=request.query_params)
        inp.is_valid(raise_exception=True)
        result = summarize_project_costs(inp.to_filters())

        paginator = ResultPaginator()
        page = paginator.paginate_queryset(result.rows, request, self)
        rows = SummaryRowSerializer(
            page,
            many=True,
            context={
                "request": request,
                "stat_range": result.stat_range,
                "last_period_range": result.last_period_range,
            },
        ).data
        data: dict[str, Any] = OrderedDict(
            paginator.get_paginated_response(cast("list[Any]", rows)).data
        )
        data["resourceTypes"] = result.resource_types
        data["summary"] = {
            "amountByResourceType": {
                code: _money_or_dash(amount)
                for code, amount in result.summary_amount_by_resource_type.items()
            },
            "totalAmount": _money_or_dash(result.summary_total),
        }
        return Response(data)


class CostDetailView(APIView):
    permission_classes = (IsAuthenticated,)  # type: ignore[assignment]

    def get(self, request: Request) -> Response:
        inp = CostQueryInputSerializer(data=request.query_params)
        inp.is_valid(raise_exception=True)
        queryset = list_bill_details(inp.to_filters())

        paginator = ResultPaginator()
        page = paginator.paginate_queryset(queryset, request, self)
        rows = MaskedDetailRowSerializer(page, many=True, context={"request": request}).data
        return paginator.get_paginated_response(cast("list[Any]", rows))


class CostTrendView(APIView):
    permission_classes = (IsAuthenticated,)  # type: ignore[assignment]

    def get(self, request: Request) -> Response:
        inp = TrendQueryInputSerializer(data=request.query_params)
        inp.is_valid(raise_exception=True)
        result = query_cost_trend(inp.to_filters())
        return Response(TrendResultSerializer(result, context={"request": request}).data)
