from django.db import models
from django.utils import timezone


class EventTypeDict(models.Model):
    """事件类型字典（database.md 表 12）：事件类型/默认级别/筛选项唯一来源。"""

    class DefaultLevel(models.TextChoices):
        INFO = "info", "提示"
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    code = models.CharField("类型代码", max_length=64)
    display_name = models.CharField("显示名", max_length=128)
    default_level = models.CharField(
        "默认级别", max_length=16, choices=DefaultLevel.choices
    )
    data_source = models.CharField("数据源说明", max_length=128, null=True, blank=True)
    enabled = models.BooleanField("启用", default=True)
    sort_order = models.IntegerField("排序", default=0)
    description = models.TextField("说明", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "event_type_dict"
        verbose_name = "事件类型字典"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uk_event_code"),
        ]

    def __str__(self) -> str:
        return self.code


class CloudEvent(models.Model):
    """事件（database.md 表 11）：uk_event_dedup 去重，厂商消息/平台自算/手工补录。"""

    class EventLevel(models.TextChoices):
        INFO = "info", "提示"
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    class Source(models.TextChoices):
        VENDOR = "vendor", "厂商消息"
        RULE = "rule", "平台自算"
        MANUAL = "manual", "手工补录"

    class Status(models.TextChoices):
        UNREAD = "unread", "未读"
        READ = "read", "已读"
        HANDLED = "handled", "已处理"
        IGNORED = "ignored", "已忽略"

    event_no = models.CharField("事件编号", max_length=64, null=True, blank=True)
    event_type = models.CharField("事件类型", max_length=64)
    event_level = models.CharField("级别", max_length=16, choices=EventLevel.choices)
    source = models.CharField("来源", max_length=16, choices=Source.choices)
    resource_type = models.CharField("资源类型", max_length=32, null=True, blank=True)
    resource_id = models.CharField("实例 ID / 域名", max_length=128, null=True, blank=True)
    instance_name = models.CharField("实例名称", max_length=256, null=True, blank=True)
    cloud_account = models.ForeignKey(
        "billing.CloudAccount",
        on_delete=models.RESTRICT,
        verbose_name="云账号",
        null=True,
        blank=True,
    )
    provider = models.CharField("厂商", max_length=32, null=True, blank=True)
    vendor_event_code = models.CharField(
        "厂商原始事件类型", max_length=64, null=True, blank=True
    )
    vendor_event_name = models.CharField(
        "厂商事件名称", max_length=128, null=True, blank=True
    )
    region = models.CharField("地域", max_length=64, null=True, blank=True)
    project_tag = models.CharField("项目标签", max_length=128, null=True, blank=True)
    title = models.CharField("标题", max_length=256)
    content = models.TextField("详情", null=True, blank=True)
    metric_json = models.JSONField("指标快照", null=True, blank=True)
    raw_payload = models.TextField("厂商原始报文（截断 4KB）", null=True, blank=True)
    occurred_at = models.DateTimeField("厂商发生时间", null=True, blank=True)
    received_at = models.DateTimeField("平台接收时间", default=timezone.now)
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.UNREAD
    )
    handled_by = models.CharField("处理人", max_length=150, null=True, blank=True)
    handled_at = models.DateTimeField("处理时间", null=True, blank=True)
    dedup_key = models.CharField("去重键", max_length=128)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "cloud_event"
        verbose_name = "事件"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["dedup_key"], name="uk_event_dedup"),
        ]
        indexes = [
            models.Index(fields=["occurred_at"], name="idx_evt_time"),
            models.Index(fields=["status", "event_level"], name="idx_evt_status_level"),
            models.Index(fields=["resource_type", "resource_id"], name="idx_evt_resource"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}/{self.title}"


class VendorMessageLog(models.Model):
    """厂商消息流水（database.md 表 13）：全量含未识别与重复，回答「为何没变成事件」。"""

    class MappedStatus(models.TextChoices):
        MAPPED = "mapped", "已映射"
        UNMAPPED = "unmapped", "未识别"
        DUPLICATED = "duplicated", "重复"

    provider = models.CharField("厂商", max_length=32)
    cloud_account = models.ForeignKey(
        "billing.CloudAccount",
        on_delete=models.RESTRICT,
        verbose_name="云账号",
        null=True,
        blank=True,
    )
    message_id = models.CharField("厂商消息 ID", max_length=128)
    vendor_event_code = models.CharField(
        "厂商原始事件类型", max_length=64, null=True, blank=True
    )
    vendor_event_name = models.CharField(
        "厂商事件名称", max_length=128, null=True, blank=True
    )
    raw_payload = models.TextField("原始报文")
    mapped_event_type = models.CharField(
        "映射后事件类型", max_length=64, null=True, blank=True
    )
    mapped_status = models.CharField(
        "映射状态", max_length=16, choices=MappedStatus.choices, null=True, blank=True
    )
    cloud_event = models.ForeignKey(
        CloudEvent,
        on_delete=models.SET_NULL,
        verbose_name="关联事件",
        null=True,
        blank=True,
    )
    occurred_at = models.DateTimeField("厂商发生时间", null=True, blank=True)
    received_at = models.DateTimeField("平台接收时间", default=timezone.now)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "vendor_message_log"
        verbose_name = "厂商消息流水"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["provider", "message_id"], name="uk_vendor_msg"),
        ]
        indexes = [
            models.Index(
                fields=["mapped_status", "received_at"], name="idx_vmsg_unmapped"
            ),
            models.Index(fields=["received_at"], name="idx_vmsg_time"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.message_id}"


class VendorMapping(models.Model):
    """厂商映射（database.md 表 14）：五类映射落库，Django Admin 直接维护。"""

    class MappingKind(models.TextChoices):
        RESOURCE_TYPE = "resource_type", "资源类型"
        REGION = "region", "地域"
        CHARGE_TYPE = "charge_type", "计费类型"
        STATUS = "status", "资产状态"
        EVENT_TYPE = "event_type", "事件类型"

    mapping_kind = models.CharField("映射类别", max_length=32, choices=MappingKind.choices)
    provider = models.CharField("厂商", max_length=32)
    vendor_code = models.CharField("厂商原始值", max_length=128)
    vendor_name = models.CharField("厂商原始名称", max_length=128, null=True, blank=True)
    standard_code = models.CharField("平台标准值", max_length=64)
    standard_name = models.CharField("平台展示名", max_length=128, null=True, blank=True)
    enabled = models.BooleanField("启用", default=True)
    remark = models.TextField("备注", null=True, blank=True)
    create_time = models.DateTimeField("创建时间", auto_now_add=True)
    update_time = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "vendor_mapping"
        verbose_name = "厂商映射"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=["mapping_kind", "provider", "vendor_code"],
                name="uk_vendor_map",
            ),
        ]
        indexes = [
            models.Index(
                fields=["mapping_kind", "provider", "vendor_code", "enabled"],
                name="idx_map_lookup",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.mapping_kind}/{self.provider}/{self.vendor_code}"
