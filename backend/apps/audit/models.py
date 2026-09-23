from django.db import models


class AuditLog(models.Model):
    """审计日志（database.md 表 6）：操作留痕，12 个月归档。"""

    class Action(models.TextChoices):
        QUERY = "query", "查询"
        EXPORT = "export", "导出"
        SYNC = "sync", "同步"
        AGGREGATE = "aggregate", "聚合"
        BUDGET_IMPORT = "budget_import", "预算导入"
        DETECT = "detect", "自算检测"
        MAINTAIN = "maintain", "分区维护"
        EVENT_HANDLE = "event_handle", "事件处理"

    operator = models.CharField("操作人", max_length=150, null=True, blank=True)
    role = models.CharField("角色", max_length=32, null=True, blank=True)
    action = models.CharField("动作", max_length=32, choices=Action.choices)
    params_snapshot = models.JSONField("参数快照", null=True, blank=True)
    result = models.CharField("结果", max_length=16, null=True, blank=True)
    client_ip = models.CharField("客户端 IP", max_length=45, null=True, blank=True)
    cost_ms = models.IntegerField("耗时（毫秒）", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        verbose_name = "审计日志"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.operator}/{self.action}/{self.create_time}"
