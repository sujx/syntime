"""仪表盘路由（api.md 接口9 聚合）。"""

from django.urls import path

from apps.core.views import DashboardView

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
]
