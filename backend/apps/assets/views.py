"""资产接口层（api.md 接口14 域名导入 / 接口16 闲置资源清单）。

域名导入：multipart CSV 上传，限成本管理员；逐行校验、部分成功不整批回滚，返回成功条数
与失败行明细（行号 + 原因）。CSV 解析在本层，落库与校验口径全在
``services.import_domains``（与 Django Admin 单条维护共用同一校验逻辑）。

闲置清单：判定实时推导、不落库，本层只做入参校验、分页与 notice 拼装，
判据口径在 ``idle_rules.judge``、读路径在 ``selectors.list_idle_assets``。
"""

from __future__ import annotations

import csv
import io
from collections import OrderedDict
from typing import Any, cast

from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.idle_rules import IDLE_NOTICE
from apps.assets.selectors import list_idle_assets
from apps.assets.serializers import IdleQueryInputSerializer, IdleRowSerializer
from apps.assets.services import import_domains
from common.api.pagination import ResultPaginator
from common.permissions import IsCostAdmin, IsCostAdminOrOps

# 单文件行数上限，防御性避免超大上传拖垮逐行 upsert（域名量级通常为几十）。
_MAX_ROWS = 5000


class DomainImportView(APIView):
    permission_classes = (IsAuthenticated, IsCostAdmin)  # type: ignore[assignment]
    parser_classes = (MultiPartParser,)  # type: ignore[assignment]

    def post(self, request: Request) -> Response:
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "缺少 CSV 文件。"})

        # utf-8-sig 兼容 Excel 导出的 BOM 头，否则首列表头会带上不可见前缀。
        text = upload.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) > _MAX_ROWS:
            raise ValidationError({"file": f"单次导入不得超过 {_MAX_ROWS} 行。"})

        result = import_domains(rows)
        return Response(
            {
                "successCount": result.success_count,
                "errors": [{"row": e.row, "reason": e.reason} for e in result.errors],
            }
        )


class IdleResourceView(APIView):
    """闲置资源清单（api.md 接口16 / PRD 3.14）。

    判定实时推导、不落库（PRD 3.14-8）。权限：仅成本管理员与云运维（财务 40300），
    因此**不需要**字段级屏蔽层。排序在判定后的全量列表上完成，分页用全局 `ResultPaginator`
    （它接受普通 list，先例见 `CostSummaryView`）；`notice` 是误报提示文案的单一来源。
    """

    permission_classes = (IsAuthenticated, IsCostAdminOrOps)

    def get(self, request: Request) -> Response:
        inp = IdleQueryInputSerializer(data=self._query_dict(request))
        inp.is_valid(raise_exception=True)
        rows = list_idle_assets(inp.to_filters())

        paginator = ResultPaginator()
        page = paginator.paginate_queryset(rows, request, self)
        page_rows = IdleRowSerializer(page, many=True).data
        data: dict[str, Any] = OrderedDict(
            paginator.get_paginated_response(cast("list[Any]", page_rows)).data
        )
        data["notice"] = IDLE_NOTICE
        return Response(data)

    @staticmethod
    def _query_dict(request: Request) -> dict[str, Any]:
        """把 QueryDict 摊平为普通 dict，idleType 用 getlist 保留多选（口径同接口12）。"""
        qp = request.query_params
        return {key: qp.getlist(key) if key == "idleType" else qp.get(key) for key in qp}
