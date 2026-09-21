"""统一分页（api.md 接口 1/2：返回 total、page、pageSize、list）。

单页上限 100 条（接口 2 显式要求，全局取同一口径）。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response


class ResultPaginator(PageNumberPagination):
    page_size = 20
    page_size_query_param = "pageSize"
    max_page_size = 100
    page_query_param = "page"

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> Any:
        self.request = request  # 覆盖写：get_paginated_response 需要 request 解析 pageSize
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data: list[Any]) -> Response:
        page = self.page  # paginate_queryset 成功后才有 page；调用方语义保证非空
        assert page is not None
        request = self.request
        assert request is not None
        return Response(
            OrderedDict(
                [
                    ("total", page.paginator.count),
                    ("page", page.number),
                    ("pageSize", self.get_page_size(request)),
                    ("list", data),
                ]
            )
        )

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "page": {"type": "integer", "nullable": True},
                "pageSize": {"type": "integer", "nullable": True},
                "list": schema,
            },
        }
