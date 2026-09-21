"""成本查询接口路由（api.md 接口1/2/8，P0）。"""

from django.urls import path

from apps.cost.views import CostDetailView, CostSummaryView, CostTrendView

urlpatterns = [
    path("summary/", CostSummaryView.as_view(), name="cost_summary"),
    path("details/", CostDetailView.as_view(), name="cost_details"),
    path("trend/", CostTrendView.as_view(), name="cost_trend"),
]
