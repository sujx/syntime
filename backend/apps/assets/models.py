from django.db import models


class CloudAsset(models.Model):
    """云资产（database.md 表 10）：全量对齐同步，released_at 软删除；域名账号可空。"""

    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        STOPPED = "stopped", "已停机"
        BOUND = "bound", "已绑定"
        UNBOUND = "unbound", "未绑定"
        NORMAL = "normal", "正常"
        ABNORMAL = "abnormal", "异常"
        EXPIRING = "expiring", "即将到期"
        EXPIRED = "expired", "已过期"
        UNKNOWN = "unknown", "未知"

    cloud_account = models.ForeignKey(
        "billing.CloudAccount",
        on_delete=models.RESTRICT,
        verbose_name="云账号",
        null=True,
        blank=True,
    )
    region = models.CharField("地域", max_length=64, null=True, blank=True)
    instance_id = models.CharField("实例 ID", max_length=128)
    instance_name = models.CharField("实例名称", max_length=256, null=True, blank=True)
    resource_type = models.CharField("资源类型", max_length=32)
    project_tag = models.CharField("项目标签", max_length=128, null=True, blank=True)
    raw_tags = models.TextField("原始标签串", null=True, blank=True)
    status = models.CharField(
        "平台标准状态", max_length=16, choices=Status.choices, default=Status.UNKNOWN
    )
    vendor_status = models.CharField("厂商原始状态", max_length=64, null=True, blank=True)
    status_changed_at = models.DateTimeField("状态变更时间", null=True, blank=True)
    spec = models.CharField("规格", max_length=128, null=True, blank=True)
    private_ip = models.CharField("内网 IP", max_length=256, null=True, blank=True)
    public_ip = models.CharField("公网 IP", max_length=256, null=True, blank=True)
    charge_type = models.CharField("计费方式", max_length=32, null=True, blank=True)
    expire_time = models.DateTimeField("到期时间", null=True, blank=True)
    registrar = models.CharField("注册商", max_length=64, null=True, blank=True)
    realname_status = models.CharField("实名状态", max_length=32, null=True, blank=True)
    dns_servers = models.CharField("DNS 服务器", max_length=256, null=True, blank=True)
    auto_renew = models.BooleanField("自动续费", null=True, blank=True)
    remark = models.TextField("备注", null=True, blank=True)
    first_seen_at = models.DateTimeField("首次发现", null=True, blank=True)
    last_seen_at = models.DateTimeField("最近发现", null=True, blank=True)
    released_at = models.DateTimeField("释放时间", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "cloud_asset"
        verbose_name = "云资产"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["cloud_account", "resource_type", "instance_id"],
                name="uk_asset",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["resource_type", "status"], name="idx_asset_type_status"),
            models.Index(fields=["project_tag"], name="idx_asset_project"),
            models.Index(fields=["cloud_account"], name="idx_asset_account"),
            models.Index(fields=["charge_type", "status"], name="idx_asset_idle"),
        ]

    def __str__(self) -> str:
        return f"{self.resource_type}/{self.instance_id}"
