"""CloudAsset 的 Django Admin（tasks.md 任务5：域名 CSV 导入 + Admin 单条维护）。

域名状态由 expire_time 推导（PRD 3.13-4），与 CSV 导入共用 ``derive_domain_status``，
避免 Admin 手填状态与导入口径分叉；非域名资源状态由同步任务映射，Admin 不重导。
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.assets.models import CloudAsset
from apps.assets.services import derive_domain_status


@admin.register(CloudAsset)
class CloudAssetAdmin(admin.ModelAdmin):
    list_display = (
        "instance_id",
        "resource_type",
        "status",
        "registrar",
        "expire_time",
        "project_tag",
        "cloud_account",
        "released_at",
    )
    list_filter = ("resource_type", "status", "auto_renew")
    search_fields = ("instance_id", "instance_name", "registrar", "project_tag")
    readonly_fields = (
        "first_seen_at",
        "last_seen_at",
        "status_changed_at",
        "create_time",
        "update_time",
    )

    def save_model(self, request: HttpRequest, obj: CloudAsset, form: Any, change: bool) -> None:
        if obj.resource_type == "domain":
            obj.status = derive_domain_status(obj.expire_time)
        super().save_model(request, obj, form, change)
