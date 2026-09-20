"""event_type_dict 字典种子数据（engineering-conventions §5.2、PRD 3.12-8）。

前四类由厂商消息映射而来，后三类由平台自算；默认级别见 PRD 3.12-5。
get_or_create 语义——已有 code 不覆盖；反向不删除。
"""

from django.db import migrations

_SEEDS = [
    # code, 显示名, 默认级别, 数据源说明
    ("arrears", "欠费", "critical", "厂商消息"),
    ("traffic_exceed", "流量过大", "warning", "厂商消息（云监控带宽/流量告警）"),
    ("renewed", "续费成功", "info", "厂商消息（订单支付/到期变更）"),
    ("stopped", "停机", "critical", "厂商消息（系统事件，Q9=B 无自算兜底）"),
    ("expiring", "即将到期", "warning", "平台自算（cloud_asset.expire_time，T-30/T-7/T-1）"),
    ("expired", "已过期", "critical", "平台自算（cloud_asset.expire_time）"),
    ("budget_overrun", "预算超支", "warning", "平台自算（project_cost_daily + project_budget）"),
]


def seed(apps, schema_editor):
    EventTypeDict = apps.get_model("events", "EventTypeDict")
    for code, display_name, default_level, data_source in _SEEDS:
        EventTypeDict.objects.get_or_create(
            code=code,
            defaults={
                "display_name": display_name,
                "default_level": default_level,
                "data_source": data_source,
                "sort_order": len(code),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
