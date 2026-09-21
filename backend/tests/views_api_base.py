"""API 基座哑元端点：仅供 tests/urls_api_base.py 挂载，验证统一返回与异常映射。"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api.pagination import ResultPaginator
from common.exceptions import BizError, SyncWindowConflictError


class EchoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"ok": True})

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        class Body(serializers.Serializer):
            hello = serializers.CharField()

        serializer = Body(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(dict(serializer.validated_data))


class RaiseBizView(APIView):
    exc: BizError = SyncWindowConflictError()
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise self.exc


class PageView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = ResultPaginator

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rows = [{"name": f"n{i}"} for i in range(50)]
        view: Any = self
        page = view.paginate_queryset(rows)
        assert page is not None
        return view.get_paginated_response(page)
