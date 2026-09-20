"""resource_type_dict 字典种子数据（engineering-conventions §5.2、PRD 3.13-1）。

ECS / RDS / EIP / NAT 为一期四类资源类型，domain 随 V1.7 域名资源纳入。
get_or_create 语义——已有 code（含管理员新增列序）不覆盖；反向不删除。
"""

from django.db import migrations

_SEEDS = [
    ("ecs", "ECS 云服务器", 1),
    ("rds", "云数据库 RDS", 2),
    ("eip", "弹性公网 IP", 3),
    ("nat", "NAT 网关", 4),
    ("domain", "域名", 5),
]


def seed(apps, schema_editor):
    ResourceTypeDict = apps.get_model("billing", "ResourceTypeDict")
    for code, display_name, sort_order in _SEEDS:
        ResourceTypeDict.objects.get_or_create(
            code=code,
            defaults={"display_name": display_name, "sort_order": sort_order},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
