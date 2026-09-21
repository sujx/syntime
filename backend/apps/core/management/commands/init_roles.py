"""初始化三角色 Group（permissions.md：成本管理员 / 云运维 / 财务人员，幂等）。

部署后执行一次即可；重复执行不产生重复组。用户-角色分配在 Django Admin 完成。
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from common.permissions import ALL_ROLES


class Command(BaseCommand):
    help = "创建三角色 Group（幂等）"

    def handle(self, *args: object, **options: object) -> None:
        existing = set(Group.objects.values_list("name", flat=True))
        for name in ALL_ROLES:
            if name not in existing:
                Group.objects.create(name=name)
                self.stdout.write(self.style.SUCCESS(f"已创建 Group：{name}"))
            else:
                self.stdout.write(f"已存在，跳过：{name}")
