"""测试专用 settings：挂测试 URLconf（真实路由 + 基座哑元端点）。"""

from config.settings.dev import *  # noqa: F403

ROOT_URLCONF = "tests.urls_api_base"
