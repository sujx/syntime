"""资产路由（api.md 接口14 域名导入 / 接口16 闲置资源清单）。"""

from django.urls import path

from apps.assets.views import DomainImportView, IdleResourceView

urlpatterns = [
    path("domains/import/", DomainImportView.as_view(), name="domain_import"),
    path("idle/", IdleResourceView.as_view(), name="idle_assets"),
]
