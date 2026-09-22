"""开发演示种子数据（仅 dev 使用，幂等：先清后种）。

清理标记：云账号 (aliyun/prod-main)、(aliyun/prod-edge) 及其关联账单/资产/事件/预算
（预算键固定集 PROJECTS）。种完后调用 aggregate_daily 覆盖写近 35 天聚合。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assets.models import CloudAsset
from apps.billing.models import CloudAccount, CloudBillDetail, ResourceTypeDict
from apps.billing.partitions import ensure_monthly_partition
from apps.cost.models import ProjectBudget, ProjectCostDaily
from apps.cost.services import aggregate_daily
from apps.events.models import CloudEvent, EventTypeDict

VENDOR = "aliyun"
ACCOUNTS: list[tuple[str, str]] = [("prod-main", "enabled"), ("prod-edge", "disabled")]
REGIONS = ["cn-shanghai", "cn-beijing"]
TYPES = [
    ("ecs", "云服务器 ECS"),
    ("rds", "云数据库 RDS"),
    ("slb", "负载均衡 SLB"),
    ("oss", "对象存储 OSS"),
]
PROJECTS = ["项目A", "项目B"]
DAYS = 35


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
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo 完成：账单 {CloudBillDetail.objects.count()} 行，"
                f"聚合写入 {inserted + updated}，事件 {CloudEvent.objects.count()}"
            )
        )

    def _clean(self) -> None:
        qs = CloudAccount.objects.filter(vendor=VENDOR, account_name__in=[a for a, _ in ACCOUNTS])
        ids = list(qs.values_list("pk", flat=True))
        CloudEvent.objects.filter(dedup_key__startswith="seed:").delete()
        CloudAsset.objects.filter(cloud_account_id__in=ids).delete()
        CloudBillDetail.objects.filter(cloud_account_id__in=ids).delete()
        ProjectCostDaily.objects.filter(cloud_account_id__in=ids).delete()
        ProjectBudget.objects.filter(project_tag__in=PROJECTS).delete()
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
                            "charge_type": "postpaid",
                            "expire_time": timezone.now() + timedelta(days=20 + i * 100),
                        },
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
