"""cloud_asset 增加 remark 备注列（database.md 表10 V1.22 补列）。

承接 tasks.md 任务5 域名导入模板的「备注」列——此前接受列头但无 backing 字段不落库，
现补 TEXT 列。附加性变更：既有行 remark 为 NULL，不影响 uk_asset 与任何口径。
状态层加字段，数据库层用 RunSQL 建列（cloud_asset 随 0001 RunSQL 建表，非 Django 管理）。
"""

from django.db import migrations, models

_NEW = "ALTER TABLE cloud_asset ADD COLUMN remark TEXT;"
_OLD = "ALTER TABLE cloud_asset DROP COLUMN remark;"


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="cloudasset",
                    name="remark",
                    field=models.TextField(blank=True, null=True, verbose_name="备注"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(sql=_NEW, reverse_sql=_OLD),
            ],
        ),
    ]
