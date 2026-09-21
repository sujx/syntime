"""API 基座测试：统一信封、错误码映射、分页、登录/登出、角色组初始化、schema 钩子。"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import Http404
from drf_spectacular.generators import SchemaGenerator
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    Throttled,
    ValidationError,
)
from rest_framework.exceptions import (
    PermissionDenied as DrfPermissionDenied,
)
from rest_framework.permissions import AllowAny
from rest_framework.test import APIRequestFactory

from common.api.pagination import ResultPaginator
from common.api.response import exception_handler, spectacular_envelope_hook
from common.exceptions import BizError
from common.permissions import ALL_ROLES
from tests.views_api_base import PageView, RaiseBizView


class _Dummy(BizError):
    code = 40001
    default_message = "哑元业务异常"


def _body(resp: Any) -> dict[str, Any]:
    payload = resp.json()
    assert set(payload) == {"code", "message", "data"}, payload
    return payload


# ---------------------------------------------------------------- 成功信封


def test_success_envelope_via_force_authenticate(api_client, user_alice):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get("/_test/api/echo/")
    assert resp.status_code == 200
    assert _body(resp) == {"code": 0, "message": "ok", "data": {"ok": True}}


def test_error_method_returns_http405_envelope(api_client, user_alice):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.delete("/_test/api/echo/")  # 未实现的方法 → 405
    assert resp.status_code == 405
    assert _body(resp)["code"] != 0


# ---------------------------------------------------------------- 错误码映射


def test_biz_error_keeps_own_code_over_http200(api_client, user_alice):
    api_client.force_authenticate(user=user_alice)
    resp = api_client.get("/_test/api/biz/")
    assert resp.status_code == 200
    assert _body(resp) == {"code": 40900, "message": "任务进行中，请勿重复提交", "data": None}


def test_enveloped_business_error_direct():
    class V(RaiseBizView):
        exc = _Dummy()
        permission_classes = [AllowAny]

    resp = V.as_view()(APIRequestFactory().get("/_test/api/biz/"))
    assert resp.status_code == 200
    assert resp.data == {"code": 40001, "message": "哑元业务异常", "data": None}


def test_validation_flattened_to_40001():
    resp = exception_handler(ValidationError({"name": ["长度不足。"], "tag": ["必填。"]}), {})
    assert resp is not None
    assert resp.status_code == 400
    assert resp.data["code"] == 40001
    assert resp.data["message"] == "name: 长度不足。；tag: 必填。"


def test_drf_exceptions_code_mapping():
    cases = {
        NotAuthenticated(): (40100, 401),
        AuthenticationFailed(): (40100, 401),
        DrfPermissionDenied(): (40300, 200),
        Throttled(wait=1): (42900, 429),
    }
    for exc, (code, http) in cases.items():
        resp = exception_handler(exc, {})
        assert resp is not None
        assert (resp.data["code"], resp.status_code) == (code, http), exc


def test_django_permission_denied_and_404():
    r1 = exception_handler(PermissionDenied(), {})
    assert r1 is not None and (r1.data["code"], r1.status_code) == (40300, 200)
    r2 = exception_handler(Http404(), {})
    assert r2 is not None and (r2.data["code"], r2.status_code) == (40001, 404)


def test_unexpected_exception_returns_none_for_django_500():
    assert exception_handler(ValueError("bug"), {}) is None


# ---------------------------------------------------------------- 分页


class _Obj:
    def __init__(self, name: str) -> None:
        self.name = name


def test_paginated_response_fields(rf):
    from rest_framework.request import Request

    paginator = ResultPaginator()
    view: Any = PageView()
    request = Request(rf.get("/_test/api/page/", {"page": "1"}))
    view.request = request
    view.paginator = paginator
    page = paginator.paginate_queryset([_Obj(f"n{i}") for i in range(50)], request, view)
    assert page is not None
    resp = paginator.get_paginated_response([o.name for o in page])
    assert resp.data["total"] == 50
    assert resp.data["page"] == 1
    assert resp.data["pageSize"] == 20
    assert len(resp.data["list"]) == 20


def test_page_size_capped_at_100(rf):
    from rest_framework.request import Request

    paginator = ResultPaginator()
    request = Request(rf.get("/_test/api/page/", {"page": "1", "pageSize": "500"}))
    assert paginator.get_page_size(request) == 100


# ---------------------------------------------------------------- 登录 / 登出


def test_login_returns_tokens_and_role(api_client, user_alice):
    resp = api_client.post(
        "/api/token/", {"username": "alice", "password": "pw-12345"}, format="json"
    )
    assert resp.status_code == 200
    payload = _body(resp)
    assert payload["code"] == 0
    data = payload["data"]
    assert set(data) == {"access", "refresh", "role", "username"}
    assert data["role"] == "成本管理员"
    assert data["username"] == "alice"


def test_login_wrong_password_40100(api_client, user_alice):
    resp = api_client.post("/api/token/", {"username": "alice", "password": "bad"}, format="json")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_login_without_group_role_none(api_client, user_norole):
    resp = api_client.post(
        "/api/token/", {"username": "bob", "password": "pw-12345"}, format="json"
    )
    assert _body(resp)["data"]["role"] is None


def test_logout_blacklists_refresh(api_client, user_alice):
    tokens = api_client.post(
        "/api/token/", {"username": "alice", "password": "pw-12345"}, format="json"
    ).json()["data"]
    out = api_client.post("/api/auth/logout/", {"refresh": tokens["refresh"]}, format="json")
    assert _body(out)["code"] == 0
    again = api_client.post("/api/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert again.json()["code"] == 40100


def test_logout_rejects_garbage_token(api_client):
    # 视图把 TokenError 转为字段校验失败 → 40001（参数校验口径）
    resp = api_client.post("/api/auth/logout/", {"refresh": "not-a-token"}, format="json")
    assert resp.json()["code"] == 40001


def test_unauthenticated_request_is_40100_envelope(api_client):
    resp = api_client.get("/_test/api/echo/")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100
    assert resp.headers.get("WWW-Authenticate")


# ---------------------------------------------------------------- 角色组


def test_init_roles_idempotent(db):
    call_command("init_roles", verbosity=0)
    call_command("init_roles", verbosity=0)
    assert sorted(Group.objects.values_list("name", flat=True)) == sorted(ALL_ROLES)


# ---------------------------------------------------------------- OpenAPI 信封


def test_spectacular_hook_wraps_schema():
    result: dict[str, Any] = {
        "paths": {
            "/api/x/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}},
                            }
                        }
                    }
                }
            }
        }
    }
    spectacular_envelope_hook(result)
    schema = result["paths"]["/api/x/"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert set(schema["properties"]) == {"code", "message", "data"}
    assert schema["properties"]["data"] == {"type": "object"}


def test_generated_schema_wraps_login_response(db):
    # 用真实 config.urls（排除测试哑元 APIView），验证钩子在完整 schema 生成链上生效
    from config.urls import urlpatterns as real_patterns

    schema = SchemaGenerator(patterns=real_patterns).get_schema(request=None, public=True)
    assert schema is not None
    login_schema = schema["paths"]["/api/token/"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert set(login_schema["properties"]) == {"code", "message", "data"}
