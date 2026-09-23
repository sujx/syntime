"""seed_demo 幂等种子测试：种入账单/资产/事件/预算并回写聚合；重复运行不翻倍不报错。"""

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.billing.models import CloudAccount, CloudBillDetail, SyncLog
from apps.core.selectors import sync_status
from apps.cost.models import ProjectCostDaily
from apps.events.models import CloudEvent


class SeedDemoTests(TestCase):
    def _run(self) -> None:
        call_command("seed_demo", stdout=StringIO())

    def test_seeds_and_aggregates(self):
        self._run()
        self.assertEqual(CloudAccount.objects.filter(account_name="prod-main").count(), 1)
        self.assertGreater(CloudBillDetail.objects.count(), 100)
        self.assertGreaterEqual(CloudEvent.objects.count(), 3)
        self.assertGreater(ProjectCostDaily.objects.count(), 0)

    def test_seeds_dashboard_sync_sources(self):
        """仪表盘同步块两处时间都要有来源：账号字段（种子直写）+ aggregate 成功审计（种子补种）。"""
        self._run()
        status = sync_status()
        self.assertIsNotNone(status.last_aggregate_time)
        accounts = {a.account_name: a for a in status.accounts}
        self.assertIsNotNone(accounts["prod-main"].last_sync_time)
        self.assertIsNotNone(accounts["prod-edge"].last_sync_time)

    def test_aggregate_audit_not_accumulated(self):
        """重复种只留一条种子聚合审计（先清后种覆盖自身标记行）。"""
        self._run()
        self._run()
        self.assertEqual(
            AuditLog.objects.filter(action=AuditLog.Action.AGGREGATE, operator="seed_demo").count(),
            1,
        )

    def test_idempotent(self):
        self._run()
        bills = CloudBillDetail.objects.count()
        accounts = CloudAccount.objects.count()
        events = CloudEvent.objects.count()
        self._run()
        self.assertEqual(CloudBillDetail.objects.count(), bills)
        self.assertEqual(CloudAccount.objects.count(), accounts)
        self.assertEqual(CloudEvent.objects.count(), events)

    def test_idempotent_after_sync_and_detect_side_effects(self):
        """冒烟期间的失败同步日志与检测事件（非 seed: 前缀）不得让再种因 RESTRICT 报错。"""
        self._run()
        account = CloudAccount.objects.get(account_name="prod-main")
        SyncLog.objects.create(
            cloud_account=account,
            sync_type=SyncLog.SyncType.MANUAL,
            bill_date_start=date.today(),
            bill_date_end=date.today(),
            status=SyncLog.Status.FAILED,
        )
        CloudEvent.objects.create(
            event_type="budget_overrun",
            event_level=CloudEvent.EventLevel.WARNING,
            source=CloudEvent.Source.RULE,
            cloud_account=account,
            title="beat 检测残留事件",
            dedup_key="detect:leftover",
        )
        self._run()
        self.assertEqual(CloudAccount.objects.filter(account_name="prod-main").count(), 1)
