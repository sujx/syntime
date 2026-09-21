"""统一返回结构与异常映射（api.md 错误码体系，permissions.md V1.5 落地说明）。

- 成功：``ResultEnvelopeRenderer`` 把 2xx 响应包装为 ``{"code": 0, "message": "ok", "data": ...}``；
- 失败：``exception_handler`` 把 ``BizError.code`` 与 DRF 标准异常映射到同一信封，
  非 5xx 保持 HTTP 200、仅以 ``code`` 区分（前端按 code 分支）；未预期异常抛真 HTTP 500
  交 Django 记日志（backend-ops.md），不吞 traceback；
- OpenAPI：drf-spectacular postprocess_hook 同步把响应 schema 包进信封，契约与运行时一致。
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from common.exceptions import BizError

logger = logging.getLogger(__name__)

# api.md 统一错误码
OK = 0
PARAM_INVALID = 40001
UNAUTHORIZED = 40100
FORBIDDEN = 40300
BUSY = 40900
RATE_LIMITED = 42900
SYSTEM_ERROR = 50000

# DRF 标准异常 → (错误码, HTTP 状态)，按 isinstance 顺序匹配（子类优先于父类）。
# 用 isinstance 而非精确类型：simplejwt 的 InvalidToken 继承 AuthenticationFailed，
# 精确匹配会漏掉它而误判 50000。
_DRF_ORDERED: tuple[tuple[type[exceptions.APIException], int, int], ...] = (
    (exceptions.ValidationError, PARAM_INVALID, status.HTTP_400_BAD_REQUEST),
    (exceptions.NotAuthenticated, UNAUTHORIZED, status.HTTP_401_UNAUTHORIZED),
    (exceptions.AuthenticationFailed, UNAUTHORIZED, status.HTTP_401_UNAUTHORIZED),
    (exceptions.PermissionDenied, FORBIDDEN, status.HTTP_200_OK),
    (exceptions.Throttled, RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS),
)


def _flat_message(detail: Any) -> str:
    """DRF detail 拍平为单行中文可读消息（含 ValidationError 字段字典）。"""
    if isinstance(detail, dict):
        parts: list[str] = []
        for field, msgs in detail.items():
            parts.append(f"{field}: {_flat_message(msgs)}")
        return "；".join(parts)
    if isinstance(detail, list):
        return "；".join(_flat_message(item) for item in detail)
    return str(detail)


def enveloped(exc: BizError | Exception, *, http_status: int = 200) -> Response:
    code = exc.code if isinstance(exc, BizError) else SYSTEM_ERROR
    message = exc.message if isinstance(exc, BizError) else str(exc)
    return Response(
        {"code": code, "message": message, "data": None},
        status=http_status,
        headers=getattr(exc, "headers", None),
    )


def _map_api_exception(exc: exceptions.APIException) -> tuple[int, int]:
    """按 isinstance 顺序把 DRF 异常映射为 (错误码, HTTP 状态)；未命中归 50000。"""
    for exc_type, code, http_status in _DRF_ORDERED:
        if isinstance(exc, exc_type):
            return code, http_status
    return SYSTEM_ERROR, exc.status_code


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """全 API 统一异常入口（settings 挂 REST_FRAMEWORK['EXCEPTION_HANDLER']）。

    约定：非 5xx 一律 HTTP 200（仅 401/404/429 等保留真实状态码供客户端拦截器识别），
    业务区分靠信封内 ``code``；未预期异常返回 None 交 Django 记 500 + traceback。
    """
    if isinstance(exc, BizError):
        return enveloped(exc)
    if isinstance(exc, Http404):
        return Response(
            {"code": PARAM_INVALID, "message": "资源不存在", "data": None},
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, PermissionDenied):
        return Response(
            {"code": FORBIDDEN, "message": "无权限访问该资源", "data": None},
            status=status.HTTP_200_OK,
        )
    if isinstance(exc, exceptions.APIException):
        code, http_status = _map_api_exception(exc)
        # 复刻 DRF 默认 handler 的头部透传：401 带 WWW-Authenticate、429 带 Retry-After，
        # 否则前端拦截器与浏览器无法识别鉴权/限流语义。
        headers: dict[str, str] = {}
        auth_header = getattr(exc, "auth_header", None)
        if auth_header:
            headers["WWW-Authenticate"] = auth_header
        wait = getattr(exc, "wait", None)
        if wait:
            headers["Retry-After"] = str(int(wait))
        return Response(
            {"code": code, "message": _flat_message(exc.detail), "data": None},
            status=http_status,
            headers=headers or None,
        )
    # 非 DRF 异常 = 程序缺陷：交 Django 处理（500 + 日志），不在此吞掉。
    return None


class ResultEnvelopeRenderer(JSONRenderer):
    """2xx 响应统一信封渲染器（全局 DEFAULT_RENDERER_CLASSES 首位）。"""

    media_type = "application/json"
    format = "envelope-json"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: Any = None,
    ) -> bytes:
        if isinstance(data, dict) and data.get("code") is not None:
            # 已是信封（exception_handler 产物）：透传，不重复包装。
            return super().render(data, accepted_media_type, renderer_context)
        return super().render(
            {"code": OK, "message": "ok", "data": data},
            accepted_media_type,
            renderer_context,
        )


def _wrap(inner: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["code", "message", "data"],
        "properties": {
            "code": {"type": "integer"},
            "message": {"type": "string"},
            "data": inner,
        },
    }


def spectacular_envelope_hook(result: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """把 OpenAPI 中所有响应 schema 包进 ``{code, message, data}``，与运行时一致。

    必须返回 result：drf-spectacular 以 ``result = hook(result=...)`` 串联后处理钩子，
    返回 None 会让整份 schema 变空。
    """
    for response in result.get("paths", {}).values():
        for operation in response.values():
            if not isinstance(operation, dict):
                continue
            for body in operation.get("responses", {}).values():
                if not isinstance(body, dict):
                    continue
                content = body.get("content", {})
                for media in content.values():
                    schema = media.get("schema")
                    if isinstance(schema, dict):
                        media["schema"] = _wrap(schema)
    return result
