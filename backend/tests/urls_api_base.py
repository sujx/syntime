"""测试专用 URLconf：真实 config.urls + 基座哑元端点（settings test 指向此处）。"""

from django.urls import path

from config.urls import urlpatterns as base_urlpatterns
from tests.views_api_base import EchoView, PageView, RaiseBizView

urlpatterns = [
    *base_urlpatterns,
    path("_test/api/echo/", EchoView.as_view()),
    path("_test/api/biz/", RaiseBizView.as_view()),
    path("_test/api/page/", PageView.as_view()),
]
