"""SPA 回退视图：把前端构建产物的 index.html 原样交给客户端路由。

本机部署拍板为 gunicorn + WhiteNoise、不装 nginx，因此站点根与深链（如 `/cost`）
都要由 Django 返回同一份 index.html，再由 react-router（`createBrowserRouter`）接管。
仅当 `settings.SPA_INDEX` 有值时才会被挂进 URL 表，见 `config/urls.py` 与 `settings/prod.py`。
"""

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest


def spa_index(request: HttpRequest) -> FileResponse:
    try:
        handle = open(str(getattr(settings, "SPA_INDEX", "")), "rb")
    except FileNotFoundError as exc:
        raise Http404("前端未构建：先执行 cd frontend && npm run build") from exc
    return FileResponse(handle, content_type="text/html; charset=utf-8")
