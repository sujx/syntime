"""域名导入接口（api.md 接口14 / tasks.md 任务5 / PRD 3.13）。

multipart CSV 上传，限成本管理员；逐行校验、部分成功不整批回滚，返回成功条数
与失败行明细（行号 + 原因）。CSV 解析在本层，落库与校验口径全在
``services.import_domains``（与 Django Admin 单条维护共用同一校验逻辑）。
"""

from __future__ import annotations

import csv
import io

from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.services import import_domains
from common.permissions import IsCostAdmin

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
