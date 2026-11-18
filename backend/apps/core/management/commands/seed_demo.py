"""开发演示种子数据（仅 dev 使用，幂等：先清后种）。

清理标记：云账号 (aliyun/prod-main)、(aliyun/prod-edge) 及其关联账单/资产/事件/预算
（预算键固定集 PROJECTS），``instance_id`` 以 ``seed-`` 开头且无归属云账号的资产（域名——
按账号 id 的那条删除覆盖不到它们，不清就成了永久孤儿行），以及本命令自身写下的聚合审计行。
种完后调用 ``aggregate_daily`` 覆盖写近 35 天聚合，并补一条 aggregate 成功审计——仪表盘
「最近聚合完成时间」以审计为唯一来源，而真实写入方是聚合任务（``cost.tasks``），种子走
服务函数不产生审计。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import cast

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, CloudBillDetail, ResourceTypeDict, SyncLog
from apps.billing.partitions import ensure_monthly_partition
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.cost.services import aggregate_daily
from apps.events.models import CloudEvent, EventTypeDict
from common.audit import record_audit

VENDOR = "aliyun"
ACCOUNTS: list[tuple[str, str]] = [("prod-main", "enabled"), ("prod-edge", "disabled")]
REGIONS = ["cn-shanghai", "cn-beijing"]
TYPES = [
    ("ecs", "ECS 云服务器"),
    ("rds", "云数据库 RDS"),
    ("eip", "弹性公网 IP"),
    ("nat", "NAT 网关"),
]
PROJECTS = ["项目A", "项目B"]
DAYS = 35
AUDIT_OPERATOR = "seed_demo"


class Command(BaseCommand):
    help = "生成开发演示数据（幂等，仅限本地/演示库）"

    def handle(self, *args, **options):  # noqa: ANN003
        today = date.today()
        start = today - timedelta(days=DAYS - 1)
        self._clean()
        self._ensure_partitions(today, start)
        accounts = self._seed_accounts()
        self._seed_dicts()
        self._seed_bills(accounts, start, today)
        self._seed_assets(accounts)
        self._seed_budgets(today)
        self._seed_events(accounts, today)
        inserted, updated = aggregate_daily(start, today)
        record_audit(
            AuditLog.Action.AGGREGATE,
            operator=AUDIT_OPERATOR,
            params={"command": "seed_demo", "start": start.isoformat(), "end": today.isoformat()},
            result="success",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo 完成：账单 {CloudBillDetail.objects.count()} 行，"
                f"聚合写入 {inserted + updated}，事件 {CloudEvent.objects.count()}"
            )
        )

    def _clean(self) -> None:
        qs = CloudAccount.objects.filter(vendor=VENDOR, account_name__in=[a for a, _ in ACCOUNTS])
        ids = list(qs.values_list("pk", flat=True))
        # 种子账号上的 RESTRICT 依赖须先于账号删除：事件含 beat 检测残留（非 seed: 前缀）与同步日志
        CloudEvent.objects.filter(
            Q(dedup_key__startswith="seed:") | Q(cloud_account_id__in=ids)
        ).delete()
        CloudAsset.objects.filter(cloud_account_id__in=ids).delete()
        # 域名等无归属账号的种子行不在上面的 ids 里，按 instance_id 前缀单独清（只碰 seed-）
        CloudAsset.objects.filter(
            cloud_account__isnull=True, instance_id__startswith="seed-"
        ).delete()
        CloudBillDetail.objects.filter(cloud_account_id__in=ids).delete()
        ProjectCostDaily.objects.filter(cloud_account_id__in=ids).delete()
        SyncLog.objects.filter(cloud_account_id__in=ids).delete()
        ProjectBudget.objects.filter(project_tag__in=PROJECTS).delete()
        # 只清本命令自己的标记行，不碰任务写入的真实审计
        AuditLog.objects.filter(action=AuditLog.Action.AGGREGATE, operator=AUDIT_OPERATOR).delete()
        qs.delete()

    def _ensure_partitions(self, today: date, start: date) -> None:
        d = date(start.year, start.month, 1)
        while d <= today:
            ensure_monthly_partition(d.year, d.month)
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)

    def _seed_accounts(self) -> list[CloudAccount]:
        out: list[CloudAccount] = []
        for name, status in ACCOUNTS:
            acc, _ = CloudAccount.objects.get_or_create(
                vendor=VENDOR,
                account_name=name,
                defaults={
                    "account_type": CloudAccount.AccountType.MAIN,
                    "ak_cipher": "seed-not-a-real-cipher",
                    "sk_cipher": "seed-not-a-real-cipher",
                    "status": status,
                    "last_sync_time": timezone.now() - timedelta(hours=6),
                },
            )
            out.append(acc)
        return out

    def _seed_dicts(self) -> None:
        """补本命令用到的资源类型字典。

        走 `get_or_create(code=...)` 是刻意选择：字典是运营可维护表，已有 code 的行不会被
        本文件的中文名改名覆盖（`display_name` 只是新建时的默认值），历史种下的 `slb` / `oss`
        行同样保留——删他人数据越界。
        """
        # 只补本命令用到的 code；历史种下的 slb/oss 行留在字典里不删（字典可运营维护）
        for i, (code, disp) in enumerate(TYPES):
            ResourceTypeDict.objects.get_or_create(
                code=code, defaults={"display_name": disp, "sort_order": i}
            )
        EventTypeDict.objects.get_or_create(
            code="budget_overrun",
            defaults={"display_name": "预算超支", "default_level": "warning"},
        )
        EventTypeDict.objects.get_or_create(
            code="domain_expiry",
            defaults={"display_name": "域名即将到期", "default_level": "warning"},
        )

    def _seed_bills(self, accounts: list[CloudAccount], start: date, today: date) -> None:
        rows: list[CloudBillDetail] = []
        day = start
        idx = 0
        while day <= today:
            for acc in accounts:
                for rt, _ in TYPES:
                    for tag in [*PROJECTS, None]:
                        idx += 1
                        amount = Decimal(20 + (idx % 17) + (day.day % 9)) / Decimal(3)
                        unassigned = tag is None
                        rows.append(
                            CloudBillDetail(
                                cloud_account=acc,
                                region=REGIONS[idx % len(REGIONS)],
                                instance_id=None if unassigned else f"seed-{rt}-{idx % 4:02d}",
                                resource_type=rt,
                                project_tag=tag,
                                tag_status=(
                                    CloudBillDetail.TagStatus.UNASSIGNED
                                    if unassigned
                                    else CloudBillDetail.TagStatus.NORMAL
                                ),
                                charge_type="postpaid" if idx % 3 else "prepaid",
                                currency="CNY",
                                amount=amount,
                                amount_cny=amount,
                                bill_date=day,
                                bill_month=day.strftime("%Y-%m"),
                            )
                        )
            day += timedelta(days=1)
        CloudBillDetail.objects.bulk_create(rows, batch_size=500)

    def _seed_assets(self, accounts: list[CloudAccount]) -> None:
        now = timezone.now()
        for acc in accounts:
            for ti, (rt, _) in enumerate(TYPES):
                for i in range(3):
                    CloudAsset.objects.get_or_create(
                        cloud_account=acc,
                        instance_id=f"seed-{rt}-{i:02d}",
                        defaults={
                            "resource_type": rt,
                            "instance_name": f"seed-{rt}-{i:02d}",
                            "region": REGIONS[(ti + i) % len(REGIONS)],
                            "project_tag": PROJECTS[(ti + i) % len(PROJECTS)],
                            "status": (
                                CloudAsset.Status.RUNNING
                                if (ti + i) % 4
                                else CloudAsset.Status.STOPPED
                            ),
                            # 两种计费方式都要有，否则 PRD 3.14-1 判据 ① 在演示库里恒空
                            "charge_type": "prepaid" if (ti + i) % 3 == 0 else "postpaid",
                            "expire_time": now + timedelta(days=20 + i * 100),
                            # D11：闲置判定依赖停机起点，种子必须写出真实语义
                            "first_seen_at": now - timedelta(days=DAYS),
                            "last_seen_at": now,
                            "status_changed_at": now - timedelta(days=1 if (ti + i) % 4 else 20),
                        },
                    )
        self._seed_idle_assets(accounts)

    def _seed_idle_assets(self, accounts: list[CloudAccount]) -> None:
        """四判据各造一行可命中样例 + 一行「停机不足阈值」反例（D13 / F063）。"""
        now = timezone.now()
        acc = accounts[0]

        def upsert(instance_id: str, **fields: object) -> None:
            # 只有 FK 查找键要收窄类型（django-stubs 不接受 `object`），其余查找它按 Any 放行
            account = cast(CloudAccount | None, fields.pop("cloud_account", acc))
            CloudAsset.objects.update_or_create(
                cloud_account=account,
                resource_type=fields.pop("resource_type"),
                instance_id=instance_id,
                defaults=fields,
            )

        upsert(
            "seed-prepaid-stopped",
            resource_type="ecs",
            instance_name="包年停机机（判据①）",
            status=CloudAsset.Status.STOPPED,
            charge_type="prepaid",
            region=REGIONS[0],
            project_tag=PROJECTS[0],
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=6),
            expire_time=now + timedelta(days=200),
        )
        upsert(
            "seed-postpaid-long",
            resource_type="ecs",
            instance_name="按量停机 21 天（判据②）",
            status=CloudAsset.Status.STOPPED,
            charge_type="postpaid",
            region=REGIONS[1],
            project_tag=PROJECTS[1],
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=21),
        )
        upsert(
            "seed-postpaid-short",
            resource_type="ecs",
            instance_name="按量停机 3 天（阈值内，不应出现在闲置清单）",
            status=CloudAsset.Status.STOPPED,
            charge_type="postpaid",
            region=REGIONS[0],
            project_tag=PROJECTS[0],
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=3),
        )
        upsert(
            "seed-eip-unbound",
            resource_type="eip",
            instance_name="未绑定 EIP（判据③）",
            status=CloudAsset.Status.UNBOUND,
            charge_type="postpaid",
            region=REGIONS[1],
            project_tag=PROJECTS[0],
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=9),
        )
        # 域名无云账号（uk_asset 的 cloud_account_id 为 NULL）；状态按 PRD 3.13-4 由到期日推导
        upsert(
            "seed-domain-expiring",
            cloud_account=None,
            resource_type="domain",
            instance_name="syntime.test",
            status=CloudAsset.Status.EXPIRING,
            charge_type=None,
            registrar="示例注册商",
            project_tag=PROJECTS[1],
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=2),
            expire_time=now + timedelta(days=12),
        )
        upsert(
            "seed-domain-expired",
            cloud_account=None,
            resource_type="domain",
            instance_name="old-syntime.test",
            status=CloudAsset.Status.EXPIRED,
            charge_type=None,
            registrar="示例注册商",
            project_tag=None,
            first_seen_at=now - timedelta(days=DAYS),
            last_seen_at=now,
            status_changed_at=now - timedelta(days=10),
            expire_time=now - timedelta(days=8),
        )

    def _seed_budgets(self, today: date) -> None:
        months = {(today.replace(day=1)).strftime("%Y-%m")}
        prev = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        months.add(prev)
        for m in months:
            ProjectBudget.objects.get_or_create(
                project_tag=PROJECTS[0], bill_month=m, defaults={"budget_amount": Decimal("300")}
            )
            ProjectBudget.objects.get_or_create(
                project_tag=PROJECTS[1],
                bill_month=m,
                defaults={"budget_amount": Decimal("2000")},
            )

    def _seed_events(self, accounts: list[CloudAccount], today: date) -> None:
        now = timezone.now()
        CloudEvent.objects.create(
            event_type="budget_overrun",
            event_level=CloudEvent.EventLevel.CRITICAL,
            source=CloudEvent.Source.RULE,
            title="项目A 本月成本已超预算",
            content=f"{today.isoformat()} 聚合检测到项目A支出超出预算 300 元。",
            project_tag=PROJECTS[0],
            cloud_account=accounts[0],
            dedup_key=f"seed:budget:{today.isoformat()}",
            occurred_at=now - timedelta(hours=2),
        )
        CloudEvent.objects.create(
            event_type="domain_expiry",
            event_level=CloudEvent.EventLevel.WARNING,
            source=CloudEvent.Source.RULE,
            title="域名 syntime.test 将于 20 天后到期",
            resource_type="domain",
            resource_id="syntime.test",
            instance_name="syntime.test",
            project_tag=PROJECTS[1],
            cloud_account=accounts[0],
            dedup_key=f"seed:domain:{today.isoformat()}",
            occurred_at=now - timedelta(hours=5),
        )
        CloudEvent.objects.create(
            event_type="account_arrears",
            event_level=CloudEvent.EventLevel.CRITICAL,
            source=CloudEvent.Source.VENDOR,
            provider=VENDOR,
            vendor_event_name="AccountInArrears",
            title="prod-edge 账号欠费告警",
            cloud_account=accounts[1],
            status=CloudEvent.Status.UNREAD,
            dedup_key=f"seed:arrears:{today.isoformat()}",
            occurred_at=now - timedelta(days=1),
        )
