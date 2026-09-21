from django.db import models


class ProjectBudget(models.Model):
    """项目预算（database.md 表 3）：预算独立存储，聚合不重复累加。"""

    project_tag = models.CharField("项目标签", max_length=128)
    bill_month = models.CharField("账期月（YYYY-MM）", max_length=7)
    budget_amount = models.DecimalField("预算金额", max_digits=20, decimal_places=8)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "project_budget"
        verbose_name = "项目预算"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["project_tag", "bill_month"], name="uk_project_month"),
        ]

    def __str__(self) -> str:
        return f"{self.project_tag}/{self.bill_month}"


class ProjectCostDaily(models.Model):
    """项目成本预聚合（database.md 表 4）：天粒度 rollup，覆盖写幂等。"""

    class TagStatus(models.TextChoices):
        NORMAL = "normal", "正常"
        UNASSIGNED = "unassigned", "未打标签"
        CONFLICT = "conflict", "标签冲突"

    stat_date = models.DateField("统计日期")
    project_tag = models.CharField("项目标签", max_length=128)
    tag_status = models.CharField("标签状态", max_length=16, choices=TagStatus.choices)
    cloud_account = models.ForeignKey(
        "billing.CloudAccount", on_delete=models.RESTRICT, verbose_name="云账号"
    )
    region = models.CharField("地域", max_length=64, null=True, blank=True)
    resource_type = models.CharField("资源类型", max_length=32)
    amount = models.DecimalField("金额", max_digits=20, decimal_places=8)
    bill_count = models.IntegerField("账单条数", default=0)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "project_cost_daily"
        verbose_name = "项目成本日聚合"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "stat_date",
                    "project_tag",
                    "tag_status",
                    "cloud_account",
                    "region",
                    "resource_type",
                ],
                name="uk_daily",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["stat_date", "project_tag"], name="idx_date_project"),
        ]

    def __str__(self) -> str:
        return f"{self.stat_date}/{self.project_tag}"


class AsyncTask(models.Model):
    """异步任务（database.md 表 5）：导出/同步/聚合作业。"""

    class TaskType(models.TextChoices):
        EXPORT = "export", "导出"
        SYNC = "sync", "同步"
        AGGREGATE = "aggregate", "聚合"

    class Status(models.TextChoices):
        PENDING = "pending", "排队中"
        RUNNING = "running", "执行中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"

    task_type = models.CharField("任务类型", max_length=64, choices=TaskType.choices)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    params_snapshot = models.JSONField("筛选条件快照", null=True, blank=True)
    data_version = models.CharField("数据版本", max_length=64, null=True, blank=True)
    file_path = models.TextField("文件路径", null=True, blank=True)
    file_size = models.BigIntegerField("文件大小", null=True, blank=True)
    expire_time = models.DateTimeField("过期时间", null=True, blank=True)
    retry_count = models.IntegerField("重试次数", default=0)
    error_msg = models.TextField("失败原因", null=True, blank=True)
    creator = models.CharField("创建人", max_length=150, null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    finish_time = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        db_table = "async_task"
        verbose_name = "异步任务"
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.task_type}/#{self.id}"
