from django.db import models


class PlatformSetting(models.Model):
    """平台配置（database.md 表 15）：读取顺序为配置表 → 代码内兜底默认值（PRD 2.6）。"""

    setting_key = models.CharField("配置键", max_length=64)
    setting_value = models.JSONField("配置值")
    remark = models.TextField("备注", null=True, blank=True)
    updated_by = models.CharField("更新人", max_length=150, null=True, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "platform_setting"
        verbose_name = "平台配置"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["setting_key"], name="uk_setting"),
        ]

    def __str__(self) -> str:
        return self.setting_key
