"""字段级数据权限统一层（PRD 4.2 字段级矩阵、permissions.md 2、§4.1）。

财务角色对实例/资源标识字段的置 null 只发生在本模块的 Serializer 基类，
禁止在视图或各业务接口内散落屏蔽逻辑（防新增接口漏配）。
接口级（页面/动作）权限用 DRF permission_classes，越权统一 40300，
随统一异常处理落地。
"""

from typing import Any

from django.contrib.auth.models import AbstractUser, AnonymousUser

ROLE_COST_ADMIN = "成本管理员"
ROLE_OPS = "云运维"
ROLE_FINANCE = "财务人员"

ALL_ROLES = (ROLE_COST_ADMIN, ROLE_OPS, ROLE_FINANCE)

# PRD 4.2：财务人员对「明细-实例ID」与「事件中心-资源标识字段」不可见（接口返回 null）
# 同时列 snake_case 与 camelCase：JSON 出参为 camelCase（如 pageSize/instanceId），
# 混入按序列化器输出键交集屏蔽，故两种命名都需登记，避免新接口漏屏蔽。
ROLE_MASKED_FIELDS: dict[str, frozenset[str]] = {
    ROLE_FINANCE: frozenset(
        {
            "instance_id",
            "resource_id",
            "instance_name",
            "instanceId",
            "resourceId",
            "instanceName",
        }
    ),
}


def get_role(user: AbstractUser | AnonymousUser | None) -> str | None:
    """返回用户所属的全局角色（三选一）；未登录或无角色返回 None。"""
    if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
        return None
    names = set(user.groups.values_list("name", flat=True))
    for role in ALL_ROLES:
        if role in names:
            return role
    return None


class RoleMaskedSerializerMixin:
    """按角色将屏蔽字段置 null 的 Serializer 混入。

    用法：``class DetailSerializer(RoleMaskedSerializerMixin, serializers.ModelSerializer)``
    序列化时需在 context 提供 ``request``；只作用于序列化器已声明的字段。
    """

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)  # type: ignore[misc]
        request = getattr(self, "context", {}).get("request")
        role = get_role(getattr(request, "user", None))
        masked = ROLE_MASKED_FIELDS.get(role or "", frozenset())
        for field in masked & data.keys():
            data[field] = None
        return data
