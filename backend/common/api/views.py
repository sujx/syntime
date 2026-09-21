"""鉴权视图（permissions.md V1.5：签发/刷新用 simplejwt 开箱能力，登出走 token 黑名单）。"""

from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from common.permissions import get_role


class AuthTokenSerializer(TokenObtainPairSerializer):
    """登录响应附带角色（Group 三选一，见 common.permissions.get_role），前端据此渲染菜单。"""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        data = super().validate(attrs)
        user = self.user
        assert user is not None
        data["role"] = cast(Any, get_role(user))
        data["username"] = cast(Any, user.get_username())
        return data


class LogoutSerializer(serializers.Serializer):
    """登出请求体：待拉黑的 refresh token。"""

    refresh = serializers.CharField()


class LoginView(TokenObtainPairView):
    serializer_class = AuthTokenSerializer
    permission_classes = (AllowAny,)  # type: ignore[assignment]


class LogoutView(APIView):
    """登出：拉黑 refresh token（黑名单随 token 轮换自动清理过期项）。"""

    permission_classes = (AllowAny,)
    serializer_class = LogoutSerializer

    @extend_schema(request=LogoutSerializer, responses={200: None})
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(cast("Any", serializer.validated_data["refresh"])).blacklist()
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": str(exc)}) from exc
        return Response(None, status=status.HTTP_200_OK)
