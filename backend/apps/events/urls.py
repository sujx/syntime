"""事件中心路由（api.md 接口12 列表 / 接口13 状态更新）。"""

from django.urls import path

from apps.events.views import EventListView, EventStatusUpdateView

urlpatterns = [
    path("", EventListView.as_view(), name="event_list"),
    path("status/", EventStatusUpdateView.as_view(), name="event_status_update"),
]
