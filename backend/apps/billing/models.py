from django.db import models


class CloudAccount(models.Model):
    """云账号（database.md 表 1）：禁止物理删除，仅停用（V1.17）。"""

    class AccountType(models.TextChoices):
        MAIN = "main", "主账号"
        SUB = "sub", "子账号"

    class Status(models.TextChoices):
        ENABLED = "enabled", "启用"
        DISABLED = "disabled", "停用"

    vendor = models.CharField("厂商", max_length=32)
    account_name = models.CharField("账号名称", max_length=128)
    account_alias = models.CharField("账号实名", max_length=128, null=True, blank=True)
    account_type = models.CharField("账号类型", max_length=16, choices=AccountType.choices)
    ak_cipher = models.TextField("AK 密文")
    sk_cipher = models.TextField("SK 密文")
    dek_id = models.CharField("数据密钥标识", max_length=64, null=True, blank=True)
    key_version = models.IntegerField("密钥版本", default=1)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.ENABLED
    )
    last_sync_time = models.DateTimeField("最近成功同步", null=True, blank=True)
    last_sync_attempt_time = models.DateTimeField("最近同步尝试", null=True, blank=True)
    last_sync_error = models.TextField("最近同步失败原因", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "cloud_account"
        verbose_name = "云账号"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["vendor", "account_name"], name="uk_account"),
        ]

    def __str__(self) -> str:
        return f"{self.vendor}/{self.account_name}"


class CloudBillDetail(models.Model):
    """云账单明细（database.md 表 2）：按 bill_date 声明式分区，uk_bill 保证同步幂等。"""

    class TagStatus(models.TextChoices):
        NORMAL = "normal", "正常"
        UNASSIGNED = "unassigned", "未打标签"
        CONFLICT = "conflict", "标签冲突"

    # 数据库真实主键为 (id, bill_date)（分区表要求，见 db/schema/001_init.sql）；
    # Django 5.2 复合主键与 AutoField 互斥，模型层用单列 id，id 由库端 identity 序列保证唯一
    id = models.BigAutoField(primary_key=True)
    cloud_account = models.ForeignKey(
        CloudAccount, on_delete=models.RESTRICT, verbose_name="云账号"
    )
    region = models.CharField("地域", max_length=64, null=True, blank=True)
    instance_id = models.CharField("实例 ID", max_length=128, null=True, blank=True)
    resource_type = models.CharField("资源类型", max_length=32)
    project_tag = models.CharField("项目标签", max_length=128, null=True, blank=True)
    raw_tags = models.TextField("原始标签串", null=True, blank=True)
    tag_status = models.CharField(
        "标签状态", max_length=16, choices=TagStatus.choices
    )
    charge_type = models.CharField("计费类型", max_length=32)
    currency = models.CharField("币种", max_length=8)
    amount = models.DecimalField("原币金额", max_digits=20, decimal_places=8)
    exchange_rate = models.DecimalField(
        "汇率", max_digits=20, decimal_places=8, null=True, blank=True
    )
    amount_cny = models.DecimalField(
        "折算人民币金额", max_digits=20, decimal_places=8, null=True, blank=True
    )
    bill_date = models.DateField("账单日期")
    bill_month = models.CharField("账期月（YYYY-MM）", max_length=7)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "cloud_bill_detail"
        verbose_name = "云账单明细"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "cloud_account",
                    "resource_type",
                    "instance_id",
                    "bill_date",
                    "charge_type",
                ],
                name="uk_bill",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["bill_date"], name="idx_bill_date"),
            models.Index(fields=["project_tag", "bill_date"], name="idx_project"),
            models.Index(
                fields=["cloud_account", "bill_date"], name="idx_account_date"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cloud_account_id}/{self.instance_id}/{self.bill_date}"


class SyncLog(models.Model):
    """账单同步日志（database.md 表 7）：uk_sync_window 防手动+自动重复触发。"""

    class SyncType(models.TextChoices):
        AUTO = "auto", "自动"
        MANUAL = "manual", "手动"

    class Status(models.TextChoices):
        RUNNING = "running", "进行中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失败"

    cloud_account = models.ForeignKey(
        CloudAccount, on_delete=models.RESTRICT, verbose_name="云账号"
    )
    sync_type = models.CharField("触发方式", max_length=16, choices=SyncType.choices)
    bill_date_start = models.DateField("账期起")
    bill_date_end = models.DateField("账期止")
    status = models.CharField("状态", max_length=16, choices=Status.choices)
    insert_count = models.IntegerField("新增条数", default=0)
    update_count = models.IntegerField("更新条数", default=0)
    error_msg = models.TextField("失败原因", null=True, blank=True)
    start_time = models.DateTimeField("开始时间", auto_now_add=True)
    end_time = models.DateTimeField("结束时间", null=True, blank=True)

    class Meta:
        db_table = "sync_log"
        verbose_name = "账单同步日志"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["cloud_account", "sync_type", "bill_date_start", "bill_date_end"],
                name="uk_sync_window",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.cloud_account_id}/{self.sync_type}/"
            f"{self.bill_date_start}~{self.bill_date_end}"
        )


class ResourceTypeDict(models.Model):
    """资源类型字典（database.md 表 8）：行转列/下拉/导出列头的唯一来源。"""

    code = models.CharField("类型代码", max_length=64)
    display_name = models.CharField("显示名", max_length=128)
    sort_order = models.IntegerField("列序", default=0)
    enabled = models.BooleanField("启用", default=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "resource_type_dict"
        verbose_name = "资源类型字典"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_code"),
        ]

    def __str__(self) -> str:
        return self.code


class ExchangeRate(models.Model):
    """汇率表（database.md 表 9）：账单入库按 bill_date 查表折算。"""

    currency = models.CharField("币种", max_length=8)
    rate_date = models.DateField("汇率日")
    rate_to_cny = models.DecimalField("对人民币汇率", max_digits=20, decimal_places=8)
    source = models.CharField("中间价来源", max_length=64, null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "exchange_rate"
        verbose_name = "汇率"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["currency", "rate_date"], name="uk_currency_date"),
        ]

    def __str__(self) -> str:
        return f"{self.currency}/{self.rate_date}"
