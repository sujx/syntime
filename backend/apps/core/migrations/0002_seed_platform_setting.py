"""platform_setting 预置配置键落库（engineering-conventions §5.2）。

默认值唯一来源为 common.readers.PLATFORM_SETTING_DEFAULTS；
get_or_create 语义——已有键（含管理员修改过的）不覆盖。
反向迁移不做删除，避免误删运营期间的修改；确需清理由人工执行。
"""

from django.db import migrations

from common.readers import PLATFORM_SETTING_DEFAULTS

_REMARKS = {
    "bandwidth_spike_threshold": "带宽费用突增阈值（比例，0.3 = 环比涨 30% 记异常）",
    "expire_notice_days": "到期提醒档位（天）：T-30 / T-7 / T-1",
    "unallocated_ratio_target": "未分配成本治理目标占比（Q3：≤5%）",
    "sync_cron": "同步调度：账单同步 / 资产同步 / 每月全量重算（crontab）",
    "audit_retention_months": "审计日志保留月数（在线 3 个月 + 归档至 12 个月）",
    "event_level_defaults": "事件默认级别覆盖（默认空，以 event_type_dict.default_level 为准）",
    "idle_stopped_days": "按量付费停机闲置判定天数（Q17，默认 14）",
}


def seed(apps, schema_editor):
    PlatformSetting = apps.get_model("core", "PlatformSetting")
    for key, value in PLATFORM_SETTING_DEFAULTS.items():
        PlatformSetting.objects.get_or_create(
            setting_key=key,
            defaults={
                "setting_value": value,
                "remark": _REMARKS.get(key, ""),
                "updated_by": "system-seed",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
