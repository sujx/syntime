"""audit_log.action 增加 'maintain'（分区维护，tasks.md 任务 6）。

沿用 0002 做法：状态层加 choices，数据库层同步放宽 CHECK 约束（约束随 0001
RunSQL 建，非 Django 管理）。附加性变更：既有动作值不受影响。
"""

from django.db import migrations, models

_ACTIONS = (
    "'query', 'export', 'sync', 'aggregate', 'budget_import', 'detect', 'maintain'"
)
_OLD_ACTIONS = "'query', 'export', 'sync', 'aggregate', 'budget_import', 'detect'"

_NEW = (
    "ALTER TABLE audit_log DROP CONSTRAINT audit_log_action_check;\n"
    f"ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_check CHECK (action IN ({_ACTIONS}));"
)
_OLD = (
    "ALTER TABLE audit_log DROP CONSTRAINT audit_log_action_check;\n"
    "ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_check "
    f"CHECK (action IN ({_OLD_ACTIONS}));"
)


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_alter_auditlog_action"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="auditlog",
                    name="action",
                    field=models.CharField(
                        choices=[
                            ("query", "查询"),
                            ("export", "导出"),
                            ("sync", "同步"),
                            ("aggregate", "聚合"),
                            ("budget_import", "预算导入"),
                            ("detect", "自算检测"),
                            ("maintain", "分区维护"),
                        ],
                        max_length=32,
                        verbose_name="动作",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(sql=_NEW, reverse_sql=_OLD),
            ],
        ),
    ]
