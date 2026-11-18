from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from common.api.views import LoginView, LogoutView
from config.spa import spa_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("api/auth/logout/", LogoutView.as_view(), name="auth_logout"),
    path("api/cost/", include("apps.cost.urls")),
    path("api/assets/", include("apps.assets.urls")),
    path("api/events/", include("apps.events.urls")),
    path("api/dashboard/", include("apps.core.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]

# 无独立静态服务器时由 Django 兜住前端深链（视图见 config/spa.py，开关见 settings/prod.py）。
# 排除这三个前缀是为了保住既有错误语义：写错的 /api/ 路径与缺失的 /static/ 文件仍 404，
# 而不是被回退成 index.html。
if getattr(settings, "SPA_INDEX", ""):
    urlpatterns.append(re_path(r"^(?!api/|admin/|static/).*$", spa_index))
